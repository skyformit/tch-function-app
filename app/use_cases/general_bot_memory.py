from __future__ import annotations

from threading import Lock
from typing import Any, Optional


_MEMORY_LOCK = Lock()
_CONVERSATION_MEMORY: dict[str, dict[str, str]] = {}
_TRUSTED_TRADE_DOCUMENT_MEMORY: dict[str, dict[str, Any]] = {}


def get_conversation_entities(conversation_id: Optional[str]) -> dict[str, str]:
    if not conversation_id:
        return {"company_name": "", "trade_license_number": ""}
    with _MEMORY_LOCK:
        stored = dict(_CONVERSATION_MEMORY.get(conversation_id, {}))
    return {
        "company_name": stored.get("company_name", ""),
        "trade_license_number": stored.get("trade_license_number", ""),
    }


def remember_conversation_entities(conversation_id: Optional[str], company_name: str = "", trade_license_number: str = "") -> None:
    if not conversation_id:
        return
    company_name = (company_name or "").strip()
    trade_license_number = (trade_license_number or "").strip()
    if not company_name and not trade_license_number:
        return
    with _MEMORY_LOCK:
        current = dict(_CONVERSATION_MEMORY.get(conversation_id, {}))
        if company_name:
            current["company_name"] = company_name
        if trade_license_number:
            current["trade_license_number"] = trade_license_number
        _CONVERSATION_MEMORY[conversation_id] = current


def clear_conversation_entities(conversation_id: Optional[str]) -> None:
    if not conversation_id:
        return
    with _MEMORY_LOCK:
        _CONVERSATION_MEMORY.pop(conversation_id, None)


def remember_trusted_trade_document(conversation_id: Optional[str], trade_document: dict[str, Any]) -> None:
    if not conversation_id or not isinstance(trade_document, dict):
        return
    with _MEMORY_LOCK:
        _TRUSTED_TRADE_DOCUMENT_MEMORY[conversation_id] = dict(trade_document)


def get_trusted_trade_document(conversation_id: Optional[str]) -> dict[str, Any]:
    if not conversation_id:
        return {}
    with _MEMORY_LOCK:
        stored = dict(_TRUSTED_TRADE_DOCUMENT_MEMORY.get(conversation_id, {}))
    return stored


def clear_trusted_trade_document(conversation_id: Optional[str]) -> None:
    if not conversation_id:
        return
    with _MEMORY_LOCK:
        _TRUSTED_TRADE_DOCUMENT_MEMORY.pop(conversation_id, None)
