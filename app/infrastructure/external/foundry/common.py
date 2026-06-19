import json
import os
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import azure.functions as func
import requests
from azure.identity import DefaultAzureCredential
from azurefunctions.extensions.http.fastapi import JSONResponse

DEFAULT_SCOPE = "https://ai.azure.com/.default"
DEFAULT_TIMEOUT_SECONDS = 60


def _bearer_token(scope: str) -> str:
    return DefaultAzureCredential().get_token(scope).token


def _json_body(req: func.HttpRequest) -> dict:
    try:
        body = req.get_json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _timeout_seconds() -> float:
    raw_timeout = os.getenv("FOUNDRY_HTTP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        return float(raw_timeout)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _responses_url(raw_url: str) -> str:
    split_url = urlsplit(raw_url)
    path = split_url.path.rstrip("/")
    if path.endswith("/responses"):
        return raw_url
    if path.endswith("/protocols/openai"):
        path = f"{path}/responses"
    return urlunsplit((split_url.scheme, split_url.netloc, path, split_url.query, split_url.fragment))


def _project_responses_url(project_endpoint: str) -> str:
    return f"{project_endpoint.rstrip('/')}/openai/v1/responses"


def _project_conversations_url(project_endpoint: str) -> str:
    return f"{project_endpoint.rstrip('/')}/openai/v1/conversations"


def _foundry_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}


def _json_response(payload: dict, status_code: int = 200) -> func.HttpResponse:
    return JSONResponse(payload, status_code=status_code)


def _sse_frame(event: Optional[str], payload: object) -> bytes:
    payload_text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    frame_parts = [f"event: {event}"] if event else []
    frame_parts.extend(f"data: {line}" for line in (payload_text.splitlines() or [""]))
    frame_parts.append("")
    return ("\n".join(frame_parts) + "\n").encode("utf-8")

