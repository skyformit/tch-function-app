import asyncio
from functools import partial
from typing import Optional

from azurefunctions.extensions.http.fastapi import Request, StreamingResponse

from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text, stream_foundry_from_text


def _body_text(body: dict) -> str:
    input_text = (body.get("input") or body.get("text") or "").strip()
    if input_text:
        return input_text

    activity = body.get("activity")
    if isinstance(activity, dict):
        return (activity.get("text") or "").strip()

    return ""


def _conversation_id(body: dict) -> Optional[str]:
    conversation_reference = body.get("conversation")
    conversation_id = body.get("conversation_id")
    if isinstance(conversation_reference, dict):
        conversation_id = conversation_reference.get("id") or conversation_id
    elif isinstance(conversation_reference, str):
        conversation_id = conversation_reference or conversation_id

    conversation_id = (conversation_id or "").strip()
    return conversation_id or None


async def _json_body(req: Request) -> dict:
    try:
        body = await req.json()
    except Exception:
        return {}

    return body if isinstance(body, dict) else {}


def _streaming_headers() -> dict:
    return {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _streaming_response(input_text: str, conversation_id: Optional[str], include, previous_response_id):
    return StreamingResponse(
        stream_foundry_from_text(
            input_text=input_text,
            conversation_id=conversation_id,
            include=include if isinstance(include, list) else None,
            previous_response_id=previous_response_id if isinstance(previous_response_id, str) and previous_response_id.strip() else None,
        ),
        media_type="text/event-stream",
        headers=_streaming_headers(),
    )


def _invoke_sync(input_text: str, conversation_id: Optional[str], include, previous_response_id):
    return asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=input_text,
            conversation_id=conversation_id,
            include=include if isinstance(include, list) else None,
            previous_response_id=previous_response_id if isinstance(previous_response_id, str) and previous_response_id.strip() else None,
            stream=None,
        )
    )


async def _invoke_foundry_workflow_impl(req: Request):
    body = await _json_body(req); activity = body.get("activity")
    if activity is not None and not isinstance(activity, dict): return _json_response({"ok": False, "error": {"code": "bad_request", "message": "'activity' must be a JSON object"}}, status_code=400)
    input_text = _body_text(body)
    if activity is None and not input_text: return _json_response({"ok": False, "error": {"code": "bad_request", "message": "Provide JSON with 'input', 'text', or 'activity'"}}, status_code=400)
    conversation_id = _conversation_id(body); include = body.get("include"); previous_response_id = body.get("previous_response_id"); stream_requested = body.get("stream") is True or str(body.get("stream")).strip().lower() in {"1", "true", "yes", "on"}
    if stream_requested: return _streaming_response(input_text, conversation_id, include, previous_response_id)
    status_code, payload = await _invoke_sync(input_text, conversation_id, include, previous_response_id)
    return _json_response(payload, status_code=status_code)


async def invoke_foundry_workflow(req: Request):
    return await _invoke_foundry_workflow_impl(req)


def register_foundry_workflow_routes(app) -> None:
    app.route(route="invoke-foundry-workflow", methods=["POST"])(invoke_foundry_workflow)
