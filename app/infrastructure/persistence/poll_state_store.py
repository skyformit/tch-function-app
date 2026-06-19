import copy
import json
import logging
import os

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from app.core.config import source_state_blob_name, source_state_container, source_state_mode

DEFAULT_POLL_STATE = {
    "last_timestamp": None,
    "last_item_id": None,
    "last_cursor": None,
    "processed_item_ids": [],
    "updated_at": None,
}

_IN_MEMORY_POLL_STATE = copy.deepcopy(DEFAULT_POLL_STATE)


def _default_poll_state() -> dict:
    return copy.deepcopy(DEFAULT_POLL_STATE)


def _poll_state_blob_client() -> BlobServiceClient:
    connection_string = (os.getenv("AzureWebJobsStorage") or "").strip()
    if not connection_string:
        raise RuntimeError("Missing AzureWebJobsStorage")
    return BlobServiceClient.from_connection_string(connection_string)


def _poll_state_from_blob(blob_client) -> dict:
    try:
        content = blob_client.download_blob().readall()
    except ResourceNotFoundError:
        return _default_poll_state()
    except Exception as exc:
        logging.warning("Unable to read poll state: %s", exc)
        return _default_poll_state()

    try:
        loaded_state = json.loads(content)
    except Exception:
        return _default_poll_state()

    return loaded_state if isinstance(loaded_state, dict) else _default_poll_state()


def _normalize_poll_state(loaded_state: dict) -> dict:
    processed_item_ids = loaded_state.get("processed_item_ids")
    if not isinstance(processed_item_ids, list):
        processed_item_ids = []
    return {
        "last_timestamp": loaded_state.get("last_timestamp"),
        "last_item_id": loaded_state.get("last_item_id"),
        "last_cursor": loaded_state.get("last_cursor"),
        "processed_item_ids": [str(item_id) for item_id in processed_item_ids if str(item_id).strip()],
        "updated_at": loaded_state.get("updated_at"),
    }


def load_poll_state() -> dict:
    if source_state_mode() == "memory":
        return copy.deepcopy(_IN_MEMORY_POLL_STATE)

    blob_client = _poll_state_blob_client().get_blob_client(
        container=source_state_container(),
        blob=source_state_blob_name(),
    )
    return _normalize_poll_state(_poll_state_from_blob(blob_client))


def _persist_poll_state(blob_client, state: dict) -> None:
    try:
        blob_client.create_container()
    except Exception:
        pass

    blob_client.upload_blob(json.dumps(state, ensure_ascii=False), overwrite=True, content_type="application/json")


def save_poll_state(state: dict) -> None:
    if source_state_mode() == "memory":
        global _IN_MEMORY_POLL_STATE
        _IN_MEMORY_POLL_STATE = json.loads(json.dumps(state, ensure_ascii=False))
        return

    blob_client = _poll_state_blob_client().get_blob_client(
        container=source_state_container(),
        blob=source_state_blob_name(),
    )
    _persist_poll_state(blob_client, state)


def _trim_processed_ids(processed_item_ids: list, item_id: str) -> list:
    return [str(existing_id) for existing_id in processed_item_ids if str(existing_id).strip() and str(existing_id) != item_id]


def remember_processed_item_id(state: dict, item_id: str, limit: int = 100) -> None:
    processed_item_ids = state.get("processed_item_ids")
    if not isinstance(processed_item_ids, list):
        processed_item_ids = []

    processed_item_ids = _trim_processed_ids(processed_item_ids, item_id)
    processed_item_ids.append(item_id)
    state["processed_item_ids"] = processed_item_ids[-limit:]
