from __future__ import annotations

import requests
import urllib3

from app.core.config import (
    validate_login_api_key,
    validate_login_api_key_header,
    validate_login_password,
    validate_login_timeout_seconds,
    validate_login_url,
    validate_login_username,
)
from app.infrastructure.external.trojan_api_client import post_json_with_retry
from app.use_cases.tbms.common import (
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_SLEEP_SECONDS,
    _TOKEN_CACHE,
    _tbms_token_cache_seconds,
    _tbms_verify_ssl,
)


def _login_missing(name: str) -> tuple[str, dict]:
    return "", {"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}


def _login_payload() -> dict:
    return {"userName": validate_login_username(), "password": validate_login_password()}


def _login_headers() -> dict:
    return {
        validate_login_api_key_header(): validate_login_api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _response_body(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"message": response.text}


def _login_error(response: requests.Response, response_body: dict) -> tuple[str, dict]:
    return "", {
        "ok": False,
        "error": {
            "code": "upstream_error",
            "message": response_body.get("message") if isinstance(response_body, dict) else response.text,
            "status_code": response.status_code,
        },
        "upstream": response_body,
    }


def _login_token(response_body: dict) -> str:
    token = (response_body.get("token") or "") if isinstance(response_body, dict) else ""
    if token:
        return token
    data = response_body.get("data") if isinstance(response_body, dict) else None
    return (data or {}).get("token") if isinstance(data, dict) else ""


def _login_result(token: str, response: requests.Response, response_body: dict) -> tuple[str, dict]:
    if not token:
        return "", {"ok": False, "error": {"code": "token_error", "message": "Login succeeded but token was missing in response"}, "upstream": response_body}
    return token, {"ok": True, "data": response_body, "status_code": response.status_code}


def _validate_login_config() -> tuple[str, str, str, str, dict | None]:
    login_url = validate_login_url()
    api_key = validate_login_api_key()
    username = validate_login_username()
    password = validate_login_password()
    if not login_url:
        return "", "", "", "", _login_missing("VALIDATE_LOGIN_URL")[1]
    if not api_key:
        return "", "", "", "", _login_missing("VALIDATE_LOGIN_API_KEY")[1]
    if not username:
        return "", "", "", "", _login_missing("VALIDATE_LOGIN_USERNAME")[1]
    if not password:
        return "", "", "", "", _login_missing("VALIDATE_LOGIN_PASSWORD")[1]
    return login_url, api_key, username, password, None


def _prepare_login_request(login_url: str, verify_ssl: bool, api_key: str, username: str, password: str):
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return post_json_with_retry(
        login_url,
        headers={validate_login_api_key_header(): api_key, "Content-Type": "application/json", "Accept": "application/json"},
        json_payload={"userName": username, "password": password},
        timeout=validate_login_timeout_seconds(),
        verify=verify_ssl,
        retry_attempts=DEFAULT_RETRY_ATTEMPTS,
        retry_sleep_seconds=DEFAULT_RETRY_SLEEP_SECONDS,
    )


def _login_request() -> tuple[str, dict]:
    login_url, api_key, username, password, config_error = _validate_login_config()
    if config_error is not None:
        return "", config_error
    verify_ssl = _tbms_verify_ssl()
    try:
        response = _prepare_login_request(login_url, verify_ssl, api_key, username, password)
    except requests.RequestException as exc:
        return "", {"ok": False, "error": {"code": "request_error", "message": f"Failed to call login endpoint: {exc}"}}
    response_body = _response_body(response)
    if response.status_code >= 400:
        return _login_error(response, response_body)
    return _login_result(_login_token(response_body), response, response_body)


def _bearer_token() -> tuple[str, dict | None]:
    import time

    now = time.time()
    cached_token = _TOKEN_CACHE.get("token") or ""
    if cached_token and now < float(_TOKEN_CACHE.get("expires_at") or 0.0):
        return cached_token, None
    token, login_result = _login_request()
    if token:
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = now + _tbms_token_cache_seconds()
        return token, None
    return "", login_result
