from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests

from app.infrastructure.external.foundry.common import _timeout_seconds


def _activity_payload(text: str, conversation_id: Optional[str], user_id: Optional[str]) -> dict:
    payload = {
        "type": "message",
        "id": f"activity-{datetime.now(timezone.utc).timestamp():.0f}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "serviceUrl": "http://localhost",
        "channelId": "web",
        "from": {"id": (user_id or "web-user").strip() or "web-user"},
        "conversation": {"id": conversation_id or f"conv-{datetime.now(timezone.utc).timestamp():.0f}"},
        "recipient": {"id": "foundry-agent"},
        "text": text,
    }
    return payload


def _response_payload(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"text": resp.text}
    return body if isinstance(body, dict) else {"text": resp.text}


def invoke_activity_workflow(url: str, text: str, conversation_id: Optional[str] = None, user_id: Optional[str] = None) -> tuple[int, dict]:
    if not url:
        return 500, {"ok": False, "error": {"code": "missing_configuration", "message": "Missing workflow URL"}}
    try:
        resp = requests.post(url, json=_activity_payload(text, conversation_id, user_id), timeout=_timeout_seconds())
    except requests.RequestException as exc:
        return 502, {"ok": False, "error": {"code": "request_error", "message": f"Failed to call workflow endpoint: {exc}"}}
    if resp.status_code >= 400:
        return resp.status_code, {"ok": False, "error": {"code": "request_error", "message": resp.text}, "workflow_response": _response_payload(resp)}
    return resp.status_code, _response_payload(resp)
