import asyncio
from functools import partial

from azurefunctions.extensions.http.fastapi import Request

from app.core.config import foundry_agent_name, foundry_project_endpoint, foundry_token_scope
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body


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
    agent_id = foundry_agent_name()
    token_scope = foundry_token_scope()
    if not project_endpoint:
        return None, _missing_configuration_response("FOUNDRY_PROJECT_ENDPOINT")
    if not agent_id:
        return None, _missing_configuration_response("FOUNDRY_AGENT_NAME")
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


async def invoke_general_bot(req: Request):
    body = await _json_body(req)
    error_code, error_message = _validate_body(body)
    if error_code:
        return _json_response({"ok": False, "error": {"code": error_code, "message": error_message}}, status_code=400)
    config, config_error = _resolve_config()
    if config_error is not None:
        return config_error
    status_code, payload = await _invoke_general_bot_workflow(body, config)
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
