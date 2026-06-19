import os
from typing import Iterator, Optional

import requests

from app.core.config import vendor_approval_workflow_url
from app.infrastructure.external.foundry.common import (
    DEFAULT_SCOPE,
    _bearer_token,
    _foundry_headers,
    _project_conversations_url,
    _project_responses_url,
    _responses_url,
    _sse_frame,
    _timeout_seconds,
)
from app.infrastructure.external.foundry.payload import _normalize_error_body, _success_payload


def _resolve_stream_url() -> str:
    project_endpoint = (os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
    if project_endpoint:
        return _project_responses_url(project_endpoint)
    raw_url = os.getenv("FOUNDRY_RESPONSES_URL") or os.getenv("FOUNDRY_PROTOCOL_URL") or os.getenv("FOUNDRY_ACTIVITYPROTOCOL_URL") or ""
    return _responses_url(raw_url)


def _stream_headers() -> dict:
    scope = (os.getenv("FOUNDRY_TOKEN_SCOPE") or DEFAULT_SCOPE).strip()
    return _foundry_headers(_bearer_token(scope))


def _stream_body(input_text: str, agent_name: str, conversation_id: Optional[str], include: Optional[list], previous_response_id: Optional[str]) -> dict:
    body = {"input": input_text, "agent_reference": {"type": "agent_reference", "name": agent_name}, "stream": True}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    if include:
        body["include"] = include
    if conversation_id:
        body["conversation"] = {"id": conversation_id}
    return body


def _conversation_meta(agent_name: str, conversation_id: str) -> bytes:
    return _sse_frame("meta", {"ok": True, "type": "conversation", "conversation_id": conversation_id, "agent": {"name": agent_name, "version": None}})


def _stream_response(resp: requests.Response, conversation_id: Optional[str], agent_name: str):
    if resp.status_code >= 400:
        yield _sse_frame("error", _normalize_error_body(resp)); return
    if "text/event-stream" in (resp.headers.get("content-type") or "").lower():
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk: yield chunk
        return
    try: payload = resp.json()
    except ValueError: payload = {}
    if isinstance(payload, dict):
        yield _sse_frame("final", _success_payload(payload, conversation_id)); return
    yield _sse_frame("final", {"ok": True, "text": resp.text, "response_id": None, "conversation_id": conversation_id, "status": "completed", "agent": {"name": agent_name, "version": None}})


def _open_stream(project_endpoint: str, url: str, headers: dict, conversation_id: Optional[str], input_text: str, agent_name: str, include: Optional[list], previous_response_id: Optional[str]) -> Iterator[bytes]:
    if project_endpoint and not conversation_id:
        conv_resp = requests.post(_project_conversations_url(project_endpoint), headers=headers, json={}, timeout=_timeout_seconds())
        if conv_resp.status_code >= 400:
            yield _sse_frame("error", _normalize_error_body(conv_resp)); return
        conversation_id = (conv_resp.json() or {}).get("id")
        if not conversation_id:
            yield _sse_frame("error", {"ok": False, "error": {"code": "conversation_error", "message": "Conversation creation did not return an id"}}); return
        yield _conversation_meta(agent_name, conversation_id)
    try:
        with requests.post(url, headers=headers, json=_stream_body(input_text, agent_name, conversation_id, include, previous_response_id), timeout=_timeout_seconds(), stream=True) as resp:
            yield from _stream_response(resp, conversation_id, agent_name)
    except requests.RequestException as exc:
        yield _sse_frame("error", {"ok": False, "error": {"code": "request_error", "message": f"Failed to call workflow endpoint: {exc}"}})


def stream_foundry_from_text(input_text: str, conversation_id: Optional[str] = None, include: Optional[list] = None, previous_response_id: Optional[str] = None) -> Iterator[bytes]:
    project_endpoint = (os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
    agent_name = (vendor_approval_workflow_url() or "").strip()
    if project_endpoint and not agent_name:
        yield _sse_frame("error", {"ok": False, "error": {"code": "missing_configuration", "message": "Missing env var: VENDOR_APPROVAL_WORKFLOW_URL"}}); return
    url = _resolve_stream_url().strip()
    if not url:
        yield _sse_frame("error", {"ok": False, "error": {"code": "missing_configuration", "message": "Missing env var: FOUNDRY_PROJECT_ENDPOINT or FOUNDRY_RESPONSES_URL (or FOUNDRY_PROTOCOL_URL / FOUNDRY_ACTIVITYPROTOCOL_URL)"}}); return
    try:
        headers = _stream_headers()
    except Exception as exc:
        yield _sse_frame("error", {"ok": False, "error": {"code": "token_error", "message": f"Failed to acquire token: {exc}"}}); return
    yield from _open_stream(project_endpoint, url, headers, conversation_id, input_text, agent_name, include, previous_response_id)
