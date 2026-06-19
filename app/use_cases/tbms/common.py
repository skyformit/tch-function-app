import asyncio
from typing import Any, Dict

import requests
import urllib3
from azurefunctions.extensions.http.fastapi import Request

from app.core.config import (
    validate_login_api_key,
    validate_login_api_key_header,
    validate_login_password,
    validate_login_timeout_seconds,
    validate_login_url,
    validate_login_username,
    validate_login_verify_ssl,
)

DEFAULT_TBMS_BASE_URL = "https://api.trojanholding.ae/Api/AI/EC"
DEFAULT_TBMS_TIMEOUT_SECONDS = 60.0
DEFAULT_TOKEN_CACHE_SECONDS = 1200.0
DEFAULT_RETRY_ATTEMPTS = 2
DEFAULT_RETRY_SLEEP_SECONDS = 1.0

_TOKEN_CACHE: Dict[str, Any] = {"token": "", "expires_at": 0.0}


def _tbms_base_url() -> str:
    return DEFAULT_TBMS_BASE_URL.rstrip("/")


def _tbms_timeout_seconds() -> float:
    return DEFAULT_TBMS_TIMEOUT_SECONDS


def _tbms_token_cache_seconds() -> float:
    return DEFAULT_TOKEN_CACHE_SECONDS


def _tbms_verify_ssl() -> bool:
    return validate_login_verify_ssl()


def _tbms_headers(token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    api_key = validate_login_api_key()
    api_key_header = validate_login_api_key_header()
    if api_key and api_key_header:
        headers[api_key_header] = api_key
    return headers


def _tbms_url(path: str) -> str:
    return f"{_tbms_base_url()}/{path.lstrip('/')}"


def _should_retry_response(response: requests.Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code < 600


async def request_json(req: Request) -> dict:
    try:
        body = await req.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def request_query_params(req: Request) -> dict:
    query_params = getattr(req, "query_params", None)
    if query_params is None:
        return {}
    try:
        return dict(query_params)
    except Exception:
        return {}

