from __future__ import annotations

import asyncio
import json
import re
from functools import partial
from typing import Any

from app.infrastructure.external.foundry_client import invoke_foundry_from_text

LOOKUP_ROUTING_PROMPT = """You are a routing classifier for a UAE business compliance assistant.

Classify the user message into exactly one routing decision:
- tbms: the user is asking to look up a vendor/company record or trade license record
- chat: the user is making general conversation or asking a non-lookup question
- clarify: the user is asking for a lookup but the message is ambiguous or missing enough lookup data

Return only valid JSON with this shape:
{
  "route": "tbms|chat|clarify",
  "lookup_type": "company_name|trade_license_number|person_name|unknown",
  "vendor_name": "string or empty",
  "license_no": "string or empty",
  "confidence": 0.0,
  "reason": "short reason"
}

Rules:
- Prefer tbms for explicit vendor/company/company name/business name/trade name/legal name inputs.
- Prefer tbms for explicit trade license/license no/license number/licence no inputs.
- Prefer tbms when the message contains a clear UAE vendor lookup intent plus a numeric license value, even if the wording is informal.
- If both company name and license number are present, extract both.
- Use clarify only when the user clearly wants a lookup but the input is incomplete or ambiguous.
- Use chat for greetings, identity questions, capability questions, and all unrelated conversations.
- Do not invent company names or license numbers.

Examples:
- "my trade license number is 206558" -> {"route":"tbms","lookup_type":"trade_license_number","vendor_name":"","license_no":"206558"}
- "vendor name Abdul Jaleel Al Saadi Trading LLC" -> {"route":"tbms","lookup_type":"company_name","vendor_name":"Abdul Jaleel Al Saadi Trading LLC","license_no":""}
- "Abdul Jaleel Al Saadi Trading LLC 206558" -> {"route":"tbms","lookup_type":"company_name","vendor_name":"Abdul Jaleel Al Saadi Trading LLC","license_no":"206558"}
- "my number is 206558" -> clarify unless the model is confident it is a lookup number
- "who are you" -> chat
"""

_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _extract_json_payload(text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return {}
    candidates = [normalized_text]
    match = _JSON_BLOCK_PATTERN.search(normalized_text)
    if match:
        candidates.insert(0, match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _normalize_decision(decision: dict[str, Any], text: str) -> dict[str, Any]:
    route = str(decision.get("route") or "chat").strip().lower()
    lookup_type = str(decision.get("lookup_type") or "unknown").strip().lower()
    vendor_name = _normalize_text(decision.get("vendor_name"))
    license_no = _normalize_text(decision.get("license_no"))
    confidence = decision.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    reason = _normalize_text(decision.get("reason")) or "LLM routing decision."
    if route not in {"tbms", "chat", "clarify"}:
        route = "chat"
    if lookup_type not in {"company_name", "trade_license_number", "person_name", "unknown"}:
        lookup_type = "unknown"
    return {
        "route": route,
        "lookup_type": lookup_type,
        "vendor_name": vendor_name,
        "license_no": license_no,
        "confidence": confidence,
        "reason": reason,
    }


def _validate_decision(decision: dict[str, Any], text: str) -> dict[str, Any]:
    route = decision.get("route")
    vendor_name = _normalize_text(decision.get("vendor_name"))
    license_no = _normalize_text(decision.get("license_no"))
    confidence = decision.get("confidence", 0.0)
    if route == "tbms" and not vendor_name and not license_no:
        return {
            "route": "clarify",
            "lookup_type": "unknown",
            "vendor_name": "",
            "license_no": "",
            "confidence": confidence if isinstance(confidence, (int, float)) else 0.0,
            "reason": "The model chose TBMS but did not provide a vendor name or license number.",
        }
    if route == "tbms" and confidence < 0.4 and not vendor_name and not license_no:
        return {
            "route": "clarify",
            "lookup_type": "unknown",
            "vendor_name": "",
            "license_no": "",
            "confidence": confidence if isinstance(confidence, (int, float)) else 0.0,
            "reason": "The model output is too weak to call TBMS safely.",
        }
    if route == "clarify" and (vendor_name or license_no):
        return {
            **decision,
            "route": "tbms",
            "reason": "The model marked the request as unclear but still extracted lookup identifiers.",
        }
    return decision


def _build_prompt(text: str) -> str:
    return f"{LOOKUP_ROUTING_PROMPT}\n\nUser message:\n{text.strip()}"


async def classify_lookup_route(text: str, config: dict) -> dict[str, Any]:
    status_code, payload = await asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=_build_prompt(text),
            conversation_id=None,
            include=None,
            previous_response_id=None,
            stream=None,
            project_endpoint=config["project_endpoint"],
            agent_id=config["agent_id"],
            token_scope=config["token_scope"],
        )
    )
    if status_code >= 400 or not isinstance(payload, dict):
        return {
            "route": "clarify",
            "lookup_type": "unknown",
            "vendor_name": "",
            "license_no": "",
            "confidence": 0.0,
            "reason": "Failed to obtain a valid routing decision from the LLM.",
        }
    decision = _extract_json_payload(payload.get("text") or "")
    if not decision:
        return {
            "route": "clarify",
            "lookup_type": "unknown",
            "vendor_name": "",
            "license_no": "",
            "confidence": 0.0,
            "reason": "The LLM did not return a valid JSON routing decision.",
        }
    normalized = _normalize_decision(decision, text)
    return _validate_decision(normalized, text)


def build_lookup_payloads(decision: dict[str, Any]) -> list[dict]:
    route = str(decision.get("route") or "").strip().lower()
    if route != "tbms":
        return []
    vendor_name = _normalize_text(decision.get("vendor_name"))
    license_no = _normalize_text(decision.get("license_no"))
    payloads: list[dict] = []
    if vendor_name and license_no:
        payloads.append({"vendorName": vendor_name, "vendId": -1, "licenseNo": license_no, "email": "", "statusId": -1})
        payloads.append({"vendorName": "", "vendId": -1, "licenseNo": license_no, "email": "", "statusId": -1})
        payloads.append({"vendorName": vendor_name, "vendId": -1, "licenseNo": "", "email": "", "statusId": -1})
        return payloads
    if license_no:
        payloads.append({"vendorName": "", "vendId": -1, "licenseNo": license_no, "email": "", "statusId": -1})
    if vendor_name:
        payloads.append({"vendorName": vendor_name, "vendId": -1, "licenseNo": "", "email": "", "statusId": -1})
    return payloads
