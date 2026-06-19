import asyncio
from functools import partial

from azurefunctions.extensions.http.fastapi import Request

from app.core.config import foundry_project_endpoint, foundry_token_scope, general_chat_agent_id
from app.infrastructure.external.foundry.activity_workflow import invoke_activity_workflow
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body
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


def _resolve_config():
    project_endpoint = foundry_project_endpoint()
    agent_id = general_chat_agent_id()
    token_scope = foundry_token_scope()
    if not project_endpoint:
        return None, _missing_configuration_response("FOUNDRY_PROJECT_ENDPOINT")
    if not agent_id:
        return None, _missing_configuration_response("GENERAL_CHAT_AGENT_ID")
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
    return _trade_license_outcome(combined, route)


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
    status_code, payload = await _invoke_general_bot_workflow(body, config)
    status_code, payload = _route_trade_license(payload, body)
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
