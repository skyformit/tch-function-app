from __future__ import annotations

import requests
from azure.functions import HttpResponse

from app.infrastructure.external.trojan_api_client import post_json_with_retry
from app.core.config import source_api_timeout_seconds
from app.use_cases.tbms.common import DEFAULT_RETRY_SLEEP_SECONDS, _tbms_headers, _tbms_url, _tbms_verify_ssl
from app.use_cases.tbms.login import _bearer_token
from core.foundry import _json_response


def _success_response(response: requests.Response) -> HttpResponse:
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text}
    return _json_response({"ok": True, "data": body, "status_code": response.status_code}, status_code=200)


def _error_response(response: requests.Response) -> HttpResponse:
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text}
    message = body.get("message") if isinstance(body, dict) else response.text
    return _json_response({"ok": False, "error": {"code": "upstream_error", "message": message, "status_code": response.status_code}, "upstream": body}, status_code=response.status_code)


def _tbms_request(token: str, endpoint_path: str, payload: dict | None, params: dict | None):
    return post_json_with_retry(
        _tbms_url(endpoint_path),
        headers=_tbms_headers(token),
        params=params or None,
        json_payload=payload or {},
        timeout=source_api_timeout_seconds(),
        verify=_tbms_verify_ssl(),
        retry_attempts=1,
        retry_sleep_seconds=DEFAULT_RETRY_SLEEP_SECONDS,
    )


def _call_tbms_api(endpoint_path: str, payload: dict | None = None, params: dict | None = None) -> HttpResponse:
    token, login_error = _bearer_token()
    if not token:
        return _json_response(login_error or {"ok": False, "error": {"code": "token_error", "message": "Failed to acquire bearer token"}}, status_code=502)
    try:
        response = _tbms_request(token, endpoint_path, payload, params)
    except requests.RequestException as exc:
        return _json_response({"ok": False, "error": {"code": "request_error", "message": f"Failed to call {endpoint_path}: {exc}"}}, status_code=502)
    if response.status_code >= 400:
        return _error_response(response)
    return _success_response(response)
