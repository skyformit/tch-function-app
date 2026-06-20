import asyncio
import json
from functools import partial

from azurefunctions.extensions.http.fastapi import Request

from app.core.config import enable_tbms_lookup, foundry_project_endpoint, foundry_token_scope, general_bot_agent_id
from app.infrastructure.external.foundry.activity_workflow import invoke_activity_workflow
from app.infrastructure.external.foundry.common import _with_response_metadata
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body
from app.use_cases.lookup_routing import build_lookup_payloads, classify_lookup_route
from app.use_cases.tbms.transport import _call_tbms_api
from app.use_cases.trade_license_routing import classify_trade_license_routing


def _missing_configuration_response(name: str):
    return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}, status_code=500)


def _validate_body(body: dict):
    activity = body.get("activity")
    if activity is not None and not isinstance(activity, dict):
        return "bad_request", "'activity' must be a JSON object"
    input_text = _body_text(body)
    if activity is None and not input_text:
        return "bad_request", "Provide JSON with 'input', 'text', or 'activity'"
    return "", ""


def _tbms_response_has_results(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return False
    data = payload.get("data")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return len(results) > 0
        if isinstance(results, dict):
            return bool(results)
        return bool(data)
    if isinstance(data, list):
        return len(data) > 0
    return bool(data)


def _lookup_clarification_response() -> dict:
    return _json_response(
        _with_response_metadata(
            {
                "ok": True,
                "status": "needs_clarification",
                "response_type": "lookup_clarification",
                "text": "Please provide the company/vendor name or trade license number.",
            },
            "backend",
        ),
        status_code=200,
    )


def _tbms_http_response_to_payload(response) -> dict:
    body = None
    body_type = None
    try:
        if hasattr(response, "get_body"):
            body = response.get_body()
        elif hasattr(response, "body"):
            body = response.body
        elif hasattr(response, "text"):
            body = response.text
        body_type = type(body).__name__ if body is not None else None
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str) and body.strip():
            return json.loads(body)
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return {
        "ok": False,
        "error": {
            "code": "response_parse_error",
            "message": "Failed to parse TBMS response",
            "body_type": body_type,
            "raw_body": body if isinstance(body, str) else None,
            "status_code": getattr(response, "status_code", None),
        },
    }


def _annotate_source(payload: dict, source: str) -> dict:
    return _with_response_metadata(payload, source)


async def _lookup_response(text: str, config: dict):
    if not enable_tbms_lookup():
        return None
    decision = await classify_lookup_route(text, config)
    if decision.get("route") == "clarify":
        return _lookup_clarification_response()
    payloads = build_lookup_payloads(decision)
    if not payloads:
        if decision.get("route") == "tbms":
            return _lookup_clarification_response()
        return None
    last_payload = None
    last_response = None
    for payload in payloads:
        last_payload = payload
        tbms_response = await asyncio.to_thread(_call_tbms_api, "GetVendorList", payload, None)
        last_response = tbms_response
        response_payload = _tbms_http_response_to_payload(tbms_response)
        if tbms_response.status_code < 400 and _tbms_response_has_results(response_payload):
            return _json_response(_annotate_source(response_payload, "tbms"), status_code=tbms_response.status_code)
    if last_response is None:
        return None
    fallback_payload = _tbms_http_response_to_payload(last_response)
    if isinstance(fallback_payload, dict):
        fallback_payload.setdefault("lookup_attempt", last_payload)
    return _json_response(_annotate_source(fallback_payload, "tbms"), status_code=last_response.status_code)


def _resolve_config():
    project_endpoint = foundry_project_endpoint()
    agent_id = general_bot_agent_id()
    token_scope = foundry_token_scope()
    if not project_endpoint:
        return None, _missing_configuration_response("FOUNDRY_PROJECT_ENDPOINT")
    if not agent_id:
        return None, _missing_configuration_response("GENERAL_BOT_AGENT_ID")
    return {"project_endpoint": project_endpoint, "agent_id": agent_id, "token_scope": token_scope}, None


def _invoke_general_bot_workflow(body: dict, config: dict):
    return asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=_body_text(body),
            conversation_id=_conversation_id(body),
            include=body.get("include") if isinstance(body.get("include"), list) else None,
            previous_response_id=body.get("previous_response_id") if isinstance(body.get("previous_response_id"), str) and body.get("previous_response_id").strip() else None,
            stream=None,
            project_endpoint=config["project_endpoint"],
            agent_id=config["agent_id"],
            token_scope=config["token_scope"],
        )
    )


def _user_id(body: dict) -> str:
    if isinstance(body.get("user_id"), str) and body["user_id"].strip():
        return body["user_id"].strip()
    activity = body.get("activity")
    if isinstance(activity, dict):
        sender = activity.get("from")
        if isinstance(sender, dict) and isinstance(sender.get("id"), str):
            return sender["id"].strip()
    return "web-user"


def _workflow_result(workflow_url: str, body: dict) -> tuple[int, dict]:
    return invoke_activity_workflow(workflow_url, _body_text(body), _conversation_id(body), _user_id(body))


def _route_trade_license(payload: dict, body: dict) -> tuple[int, dict]:
    route = classify_trade_license_routing(payload.get("text") or "")
    return (200, payload) if route is None else _route_trade_license_payload(payload, body, route)


def _route_trade_license_payload(payload: dict, body: dict, route) -> tuple[int, dict]:
    workflow_status, workflow_payload = _workflow_result(route.workflow_url, body)
    return 200, _trade_license_payload(payload, route, workflow_status, workflow_payload)


def _trade_license_payload(payload: dict, route, workflow_status: int, workflow_payload: dict) -> dict:
    combined = dict(payload)
    combined["routing"] = _trade_license_routing(route)
    combined["workflow_started"] = workflow_status < 400
    combined["workflow_response"] = workflow_payload
    combined["text"] = route.message
    return _trade_license_outcome(_with_response_metadata(combined, "workflow"), route)


def _trade_license_routing(route) -> dict:
    return {
        "expiry_date": route.decision.expiry_date.isoformat(),
        "days_remaining": route.decision.days_remaining,
        "status": route.decision.status,
        "workflow_name": route.workflow_name,
    }


def _trade_license_outcome(combined: dict, route) -> dict:
    if route.decision.status == "expired":
        combined["ok"] = False
        combined["status"] = "expired"
        combined["error"] = {"code": "trade_license_expired", "message": route.message}
        return combined
    combined["status"] = "renewal_due"
    combined["warning"] = {"code": "trade_license_renewal_due", "message": route.message}
    return combined


async def invoke_general_bot(req: Request):
    body = await _json_body(req)
    error_code, error_message = _validate_body(body)
    if error_code:
        return _json_response({"ok": False, "error": {"code": error_code, "message": error_message}}, status_code=400)
    config, config_error = _resolve_config()
    if config_error is not None:
        return config_error
    lookup_response = await _lookup_response(_body_text(body), config)
    if lookup_response is not None:
        return lookup_response
    status_code, payload = await _invoke_general_bot_workflow(body, config)
    payload = _annotate_source(payload, "llm")
    status_code, payload = _route_trade_license(payload, body)
    if isinstance(payload, dict) and "source" not in payload:
        payload["source"] = "llm"
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
