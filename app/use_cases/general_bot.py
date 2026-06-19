import asyncio
import os
from functools import partial

from azurefunctions.extensions.http.fastapi import Request

from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body


def _env(name: str, fallback: str = "") -> str:
    return (os.getenv(name) or fallback).strip()


def _project_endpoint() -> str:
    return _env("GENERAL_BOT_PROJECT_ENDPOINT") or _env("AZURE_EXISTING_AIPROJECT_ENDPOINT")


def _agent_id() -> str:
    return _env("GENERAL_BOT_AGENT_ID") or _env("AZURE_EXISTING_AGENT_ID")


def _token_scope() -> str:
    return _env("GENERAL_BOT_TOKEN_SCOPE") or _env("FOUNDRY_TOKEN_SCOPE", "https://ai.azure.com/.default")


async def invoke_general_bot(req: Request):
    body = await _json_body(req)
    activity = body.get("activity")
    if activity is not None and not isinstance(activity, dict):
        return _json_response({"ok": False, "error": {"code": "bad_request", "message": "'activity' must be a JSON object"}}, status_code=400)

    input_text = _body_text(body)
    if activity is None and not input_text:
        return _json_response({"ok": False, "error": {"code": "bad_request", "message": "Provide JSON with 'input', 'text', or 'activity'"}}, status_code=400)

    project_endpoint = _project_endpoint()
    agent_id = _agent_id()
    if not project_endpoint:
        return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": "Missing env var: GENERAL_BOT_PROJECT_ENDPOINT or AZURE_EXISTING_AIPROJECT_ENDPOINT"}}, status_code=500)
    if not agent_id:
        return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": "Missing env var: GENERAL_BOT_AGENT_ID or AZURE_EXISTING_AGENT_ID"}}, status_code=500)

    status_code, payload = await asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=input_text,
            conversation_id=_conversation_id(body),
            include=body.get("include") if isinstance(body.get("include"), list) else None,
            previous_response_id=body.get("previous_response_id") if isinstance(body.get("previous_response_id"), str) and body.get("previous_response_id").strip() else None,
            stream=None,
            project_endpoint=project_endpoint,
            agent_id=agent_id,
            token_scope=_token_scope(),
        )
    )
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
