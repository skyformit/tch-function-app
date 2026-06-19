import requests
from typing import Optional


def _extract_assistant_text(response_payload: dict) -> str:
    output_text = (response_payload.get("output_text") or "").strip()
    if output_text:
        return output_text
    for item in response_payload.get("output") or []:
        if isinstance(item, dict) and item.get("role") == "assistant":
            for content_item in item.get("content") or []:
                if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                    text = (content_item.get("text") or "").strip()
                    if text:
                        return text
    return ""


def _normalize_error_body(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text}
    if not isinstance(body, dict):
        body = {"message": response.text}
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    return {"ok": False, "error": {"code": error.get("code") if isinstance(error, dict) else None, "message": error.get("message") if isinstance(error, dict) else response.text, "type": error.get("type") if isinstance(error, dict) else None, "request_id": response.headers.get("x-request-id"), "status_code": response.status_code}}


def _success_payload(response_payload: dict, fallback_conversation_id: Optional[str] = None) -> dict:
    agent_reference = response_payload.get("agent_reference") if isinstance(response_payload.get("agent_reference"), dict) else {}
    conversation = response_payload.get("conversation") if isinstance(response_payload.get("conversation"), dict) else {}
    return {"ok": True, "text": _extract_assistant_text(response_payload), "response_id": response_payload.get("id"), "conversation_id": conversation.get("id") or fallback_conversation_id, "status": response_payload.get("status"), "agent": {"name": agent_reference.get("name"), "version": agent_reference.get("version")}}
