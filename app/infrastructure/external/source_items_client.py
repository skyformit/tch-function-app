from typing import Optional

import requests

from app.core.config import (
    source_api_key,
    source_api_key_header,
    source_api_timeout_seconds,
    source_api_url,
)


def _source_headers() -> dict:
    return {source_api_key_header(): source_api_key(), "Accept": "application/json"}


def _source_params(last_timestamp: Optional[str], last_cursor: Optional[str]) -> dict:
    params = {}
    if last_timestamp:
        params["since"] = last_timestamp
    if last_cursor:
        params["cursor"] = last_cursor
    return params


def _source_response(source_url: str, headers: dict, params: dict) -> requests.Response:
    return requests.get(source_url, headers=headers, params=params or None, timeout=source_api_timeout_seconds())


def fetch_source_payload(last_timestamp: Optional[str] = None, last_cursor: Optional[str] = None) -> dict:
    source_url = source_api_url()
    if not source_url:
        raise RuntimeError("Missing SOURCE_API_URL")

    response = _source_response(source_url, _source_headers(), _source_params(last_timestamp, last_cursor))
    if response.status_code >= 400:
        raise RuntimeError(f"Source API error {response.status_code}: {response.text}")

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Source API returned invalid JSON: {exc}") from exc
