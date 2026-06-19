import json
from datetime import datetime, timezone
from typing import Optional

from azurefunctions.extensions.http.fastapi import JSONResponse, Request

from app.infrastructure.external.source_items_client import fetch_source_payload
from app.infrastructure.persistence.poll_state_store import (
    load_poll_state,
    remember_processed_item_id,
    save_poll_state,
)
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: object):
    if not isinstance(value, str) or not value.strip():
        return None

    normalized_value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_first_value(item: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _extract_item_id(item: dict) -> str:
    value = _extract_first_value(item, ("id", "item_id", "record_id", "external_id", "uuid"))
    return str(value).strip() if value is not None else ""


def _extract_item_timestamp(item: dict):
    value = _extract_first_value(
        item,
        (
            "created_at",
            "createdAt",
            "inserted_at",
            "insertedAt",
            "updated_at",
            "updatedAt",
            "timestamp",
            "event_time",
        ),
    )
    return _parse_timestamp(value)


def _item_to_prompt(item: dict) -> str:
    for key in ("summary", "title", "name", "text", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return json.dumps(item, ensure_ascii=False, default=str)


def _payload_items(payload: object) -> list:
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else []
    for candidate_key in ("items", "data", "records", "value", "results"):
        candidate_items = payload.get(candidate_key)
        if isinstance(candidate_items, list):
            return candidate_items
    return []


def _payload_cursor(payload: object) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    next_cursor = payload.get("next_cursor") or payload.get("nextCursor") or payload.get("cursor")
    return str(next_cursor).strip() if next_cursor is not None else None


def _normalized_source_items(payload: object) -> tuple[list, Optional[str]]:
    items = [item for item in _payload_items(payload) if isinstance(item, dict)]
    items.sort(key=lambda item: (_extract_item_timestamp(item) or datetime.fromtimestamp(0, tz=timezone.utc), _extract_item_id(item)))
    return items, _payload_cursor(payload)


def _load_source_items(state: dict) -> tuple[list, Optional[str]]:
    payload = fetch_source_payload(state.get("last_timestamp"), state.get("last_cursor"))
    return _normalized_source_items(payload)


def _poll_result(ok: bool, items_seen: int, processed_count: int, skipped_count: int, failed_item, state: dict) -> dict:
    return {
        "ok": ok,
        "items_seen": items_seen,
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "failed_item": failed_item,
        "watermark": state,
    }


def _persist_progress(state: dict, next_cursor: Optional[str], last_processed_timestamp: Optional[str], last_processed_item_id: Optional[str], item_id: str) -> None:
    if last_processed_timestamp:
        state["last_timestamp"] = last_processed_timestamp
    if last_processed_item_id:
        state["last_item_id"] = last_processed_item_id
    state["last_cursor"] = next_cursor or state.get("last_cursor")
    if item_id:
        remember_processed_item_id(state, item_id)
    state["updated_at"] = _utc_now_iso()
    save_poll_state(state)


def _failed_poll_item(item_id: str, item: dict, status_code: int, foundry_payload: dict) -> dict:
    return {
        "item_id": item_id or None,
        "source_item": item,
        "foundry_status": status_code,
        "foundry_error": foundry_payload,
    }


def _process_poll_item(item: dict, processed_item_ids: set, state: dict, next_cursor: Optional[str], processed_count: int, skipped_count: int, last_processed_timestamp: Optional[str], last_processed_item_id: Optional[str]):
    item_id = _extract_item_id(item)
    if item_id and item_id in processed_item_ids:
        return processed_count, skipped_count + 1, last_processed_timestamp, last_processed_item_id, None
    status_code, foundry_payload = invoke_foundry_from_text(_item_to_prompt(item))
    if status_code >= 400 or not foundry_payload.get("ok"):
        return processed_count, skipped_count, last_processed_timestamp, last_processed_item_id, _failed_poll_item(item_id, item, status_code, foundry_payload)
    item_timestamp = _extract_item_timestamp(item)
    if item_timestamp: last_processed_timestamp = item_timestamp.isoformat()
    if item_id: last_processed_item_id = item_id; processed_item_ids.add(item_id)
    processed_count += 1; _persist_progress(state, next_cursor, last_processed_timestamp, last_processed_item_id, item_id)
    return processed_count, skipped_count, last_processed_timestamp, last_processed_item_id, None


def _run_external_poll_cycle() -> dict:
    state = load_poll_state(); items, next_cursor = _load_source_items(state); processed_item_ids = set(state.get("processed_item_ids", [])); processed_count = skipped_count = 0; last_processed_item_id = state.get("last_item_id"); last_processed_timestamp = state.get("last_timestamp")
    if not items:
        if next_cursor:
            state["last_cursor"] = next_cursor; state["updated_at"] = _utc_now_iso(); save_poll_state(state)
        return _poll_result(True, 0, 0, 0, None, state)
    for item in items:
        processed_count, skipped_count, last_processed_timestamp, last_processed_item_id, failed_item = _process_poll_item(item, processed_item_ids, state, next_cursor, processed_count, skipped_count, last_processed_timestamp, last_processed_item_id)
        if failed_item:
            return _poll_result(False, len(items), processed_count, skipped_count, failed_item, state)
    return _poll_result(True, len(items), processed_count, skipped_count, None, state)


async def poll_external_items_http(req: Request) -> JSONResponse:
    try:
        result = _run_external_poll_cycle()
        return _json_response(result, status_code=200 if result.get("ok") else 502)
    except Exception as exc:
        return _json_response(
            {
                "ok": False,
                "error": {
                    "code": "poll_error",
                    "message": str(exc),
                },
            },
            status_code=500,
        )
