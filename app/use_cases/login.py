from __future__ import annotations

import urllib3

import azure.functions as func

from app.core.config import (
    validate_login_api_key,
    validate_login_api_key_header,
    validate_login_password,
    validate_login_timeout_seconds,
    validate_login_url,
    validate_login_username,
    validate_login_verify_ssl,
)
from app.infrastructure.external.trojan_api_client import post_json_with_retry
from core.foundry import _json_response


def _missing_config_response(name: str) -> func.HttpResponse:
    return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}, status_code=500)


def _login_payload(username: str, password: str) -> dict:
    return {"userName": username, "password": password}


def _login_headers(api_key: str) -> dict:
    return {
        validate_login_api_key_header(): api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _response_body(response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"message": response.text}


def _upstream_error(response, response_body: dict) -> func.HttpResponse:
    return _json_response(
        {
            "ok": False,
            "error": {
                "code": "upstream_error",
                "message": response_body.get("message") if isinstance(response_body, dict) else response.text,
                "status_code": response.status_code,
            },
            "upstream": response_body,
        },
        status_code=response.status_code,
    )


def _success_response(response, response_body: dict) -> func.HttpResponse:
    return _json_response({"ok": True, "data": response_body, "status_code": response.status_code}, status_code=200)


def _validate_login_config() -> tuple[str, str, str, str, func.HttpResponse | None]:
    source_url = validate_login_url() or "https://api.trojanholding.ae/Api/AI/EC/ValidateLogin"
    api_key = validate_login_api_key()
    username = validate_login_username()
    password = validate_login_password()
    if not source_url:
        return "", "", "", "", _missing_config_response("VALIDATE_LOGIN_URL")
    if not api_key:
        return "", "", "", "", _missing_config_response("VALIDATE_LOGIN_API_KEY")
    if not username:
        return "", "", "", "", _missing_config_response("VALIDATE_LOGIN_USERNAME")
    if not password:
        return "", "", "", "", _missing_config_response("VALIDATE_LOGIN_PASSWORD")
    return source_url, api_key, username, password, None


def _call_login_endpoint(source_url: str, api_key: str, username: str, password: str, verify_ssl: bool):
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return post_json_with_retry(
        source_url,
        headers=_login_headers(api_key),
        json_payload=_login_payload(username, password),
        timeout=float(validate_login_timeout_seconds()),
        verify=verify_ssl,
    )


def _validate_login_impl() -> func.HttpResponse:
    source_url, api_key, username, password, config_error = _validate_login_config()
    if config_error is not None:
        return config_error
    try:
        response = _call_login_endpoint(source_url, api_key, username, password, validate_login_verify_ssl())
    except Exception as exc:
        return _json_response({"ok": False, "error": {"code": "request_error", "message": f"Failed to call login endpoint: {exc}"}}, status_code=502)
    response_body = _response_body(response)
    return _upstream_error(response, response_body) if response.status_code >= 400 else _success_response(response, response_body)


def validate_login() -> func.HttpResponse:
    return _validate_login_impl()
