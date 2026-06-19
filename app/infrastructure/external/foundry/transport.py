import os
from typing import Optional

import requests

from app.infrastructure.external.foundry.common import (
    DEFAULT_SCOPE,
    _bearer_token,
    _foundry_headers,
    _json_response,
    _project_conversations_url,
    _project_responses_url,
    _responses_url,
    _timeout_seconds,
)
from app.infrastructure.external.foundry.payload import _normalize_error_body, _success_payload
from app.core.config import vendor_approval_workflow_url


def _missing_config(message: str) -> tuple[int, dict]:
    return 500, {"ok": False, "error": {"code": "missing_configuration", "message": message}}


def _workflow_url(project_endpoint: Optional[str] = None, agent_name: Optional[str] = None) -> tuple[int, Optional[str]]:
    project_endpoint = (project_endpoint if project_endpoint is not None else os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
    agent_name = (agent_name if agent_name is not None else vendor_approval_workflow_url() or "").strip()
    if project_endpoint and not agent_name:
        return _missing_config("Missing env var: VENDOR_APPROVAL_WORKFLOW_URL")[0], None
    if project_endpoint:
        return 200, _project_responses_url(project_endpoint)
    raw_url = os.getenv("FOUNDRY_RESPONSES_URL") or os.getenv("FOUNDRY_PROTOCOL_URL") or os.getenv("FOUNDRY_ACTIVITYPROTOCOL_URL") or ""
    return 200, _responses_url(raw_url)


def _resolve_agent_name(agent_name: Optional[str] = None) -> str:
    return (agent_name if agent_name is not None else vendor_approval_workflow_url() or "").strip()


def _resolve_conversation_id(project_endpoint: str, headers: dict) -> tuple[bool, Optional[str], Optional[dict]]:
    conv_resp = requests.post(_project_conversations_url(project_endpoint), headers=headers, json={}, timeout=_timeout_seconds())
    if conv_resp.status_code >= 400:
        return False, None, _normalize_error_body(conv_resp)
    conversation_id = (conv_resp.json() or {}).get("id")
    if not conversation_id:
        return False, None, {"ok": False, "error": {"code": "conversation_error", "message": "Conversation creation did not return an id"}}
    return True, conversation_id, None


def _build_request_body(
    input_text: str,
    agent_name: str,
    stream: Optional[bool],
    previous_response_id: Optional[str],
    include: Optional[list],
    agent_id: Optional[str] = None,
) -> dict:
    agent_reference = {"type": "agent_reference"}
    if agent_id:
        if ":" in agent_id:
            agent_name_part, agent_version = agent_id.split(":", 1)
            agent_reference["name"] = agent_name_part
            agent_reference["version"] = agent_version
        else:
            agent_reference["name"] = agent_id
    else:
        agent_reference["name"] = agent_name
    body = {"input": input_text, "agent_reference": agent_reference}
    if stream is not None:
        body["stream"] = bool(stream)
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    if include:
        body["include"] = include
    return body


def _request_headers(token_scope: Optional[str] = None) -> dict:
    scope = (token_scope if token_scope is not None else os.getenv("FOUNDRY_TOKEN_SCOPE") or DEFAULT_SCOPE).strip()
    return _foundry_headers(_bearer_token(scope))


def _post_workflow(url: str, headers: dict, body: dict) -> requests.Response:
    return requests.post(url, headers=headers, json=body, timeout=_timeout_seconds())


def _maybe_resolve_conversation(project_endpoint: str, conversation_id: Optional[str], headers: dict) -> tuple[Optional[int], Optional[str], Optional[dict]]:
    if conversation_id:
        return None, conversation_id, None
    ok, resolved_conversation_id, error = _resolve_conversation_id(project_endpoint, headers)
    if not ok:
        return 502, None, error
    return None, resolved_conversation_id, None


def _response_from_http(resp: requests.Response, conversation_id: Optional[str], agent_name: str) -> tuple[int, dict]:
    if resp.status_code >= 400:
        return resp.status_code, _normalize_error_body(resp)
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        return 200, _success_payload(payload, conversation_id)
    return 200, {"ok": True, "text": resp.text, "response_id": None, "conversation_id": conversation_id, "status": "completed", "agent": {"name": agent_name, "version": None}}


def _invoke_with_context(
    url: str,
    headers: dict,
    conversation_id: Optional[str],
    input_text: str,
    agent_name: str,
    include: Optional[list],
    previous_response_id: Optional[str],
    stream: Optional[bool],
    agent_id: Optional[str] = None,
) -> tuple[int, dict]:
    body = _build_request_body(input_text, agent_name, stream, previous_response_id, include, agent_id)
    if conversation_id:
        body["conversation"] = {"id": conversation_id}
    try:
        resp = _post_workflow(url, headers, body)
    except requests.RequestException as exc:
        return 502, {"ok": False, "error": {"code": "request_error", "message": f"Failed to call workflow endpoint: {exc}"}}
    return _response_from_http(resp, conversation_id, agent_name)


def invoke_foundry_from_text(
    input_text: str,
    conversation_id: Optional[str] = None,
    include: Optional[list] = None,
    previous_response_id: Optional[str] = None,
    stream: Optional[bool] = None,
    project_endpoint: Optional[str] = None,
    agent_name: Optional[str] = None,
    agent_id: Optional[str] = None,
    token_scope: Optional[str] = None,
) -> tuple[int, dict]:
    status_code, url = _workflow_url(project_endpoint=project_endpoint, agent_name=agent_name)
    if not url:
        return status_code, {"ok": False, "error": {"code": "missing_configuration", "message": "Missing env vars for Foundry workflow"}}
    try:
        headers = _request_headers(token_scope=token_scope)
    except Exception as exc:
        return 502, {"ok": False, "error": {"code": "token_error", "message": f"Failed to acquire token: {exc}"}}
    resolved_project_endpoint = (project_endpoint if project_endpoint is not None else os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
    resolved_agent_name = _resolve_agent_name(agent_name)
    if resolved_project_endpoint:
        status_code, conversation_id, error = _maybe_resolve_conversation(resolved_project_endpoint, conversation_id, headers)
        if error:
            return status_code or 502, error
    return _invoke_with_context(url, headers, conversation_id, input_text, resolved_agent_name, include, previous_response_id, stream, agent_id)
