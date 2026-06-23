import asyncio
import json
import re
from copy import deepcopy
from functools import partial
from typing import Optional

import azure.functions as func
from azurefunctions.extensions.http.fastapi import Request

from app.core.config import enable_tbms_lookup, foundry_project_endpoint, foundry_token_scope, general_bot_agent_id
from app.infrastructure.external.foundry.activity_workflow import invoke_activity_workflow
from app.infrastructure.external.foundry.common import _with_response_metadata
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.company_name_matching import compare_company_names, normalize_company_name as _canonical_company_name
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body
from app.use_cases.general_bot_memory import (
    clear_conversation_entities,
    clear_trusted_trade_document,
    get_conversation_entities,
    get_trusted_trade_document,
    remember_conversation_entities,
)
from app.use_cases.lookup_routing import build_lookup_payloads, classify_lookup_route
from app.use_cases.tbms.transport import _call_tbms_api
from app.use_cases.trade_license_routing import classify_trade_license_routing


GENERAL_BOT_SYSTEM_PROMPT = """You are a UAE supplier onboarding and compliance assistant for Trojan Construction Holdings.

Return ONLY valid JSON with this exact shape:
{
  "ok": true,
  "text": "Human-readable reply to the user",
  "context": {
    "intent": "chat|lookup|document|clarify",
    "document_type": "unknown|trade|vat|bank|bank_offer|other",
    "entities": {
      "company_name": "",
      "trade_license_number": ""
    },
    "next_action": "general_chat|tbms_lookup|document_review|workflow|ask_clarification",
    "classification": {
      "label": "company_name|trade_license_number|person_name|unknown",
      "confidence": 0.0,
      "reason": ""
    }
  }
}

Rules:
- Use the current user message as the primary input.
- Extract company_name only when it is explicit or clearly stated.
- Do not copy the full user sentence into company_name.
- Do not include trailing business suffixes in company_name, such as trading, LLC, L.L.C, CO., company, corporation, branch, establishment, or sole proprietorship.
- Return the shortest clean company name that still identifies the business.
- Keep trade_license_number empty unless a license-like value is present.
- Set next_action to tbms_lookup only when the user is asking about a company or license lookup.
- Set next_action to general_chat for greetings and general conversation.
- If you are unsure, choose chat/unknown/general_chat.
- Do not output markdown, code fences, or extra commentary.
"""

_CONTEXT_MODES = {"fresh", "continue", "lookup", "document_review", "chat", "workflow"}
_SUPPLIER_TOPIC_HINTS = (
    "company",
    "vendor",
    "trade license",
    "trade licence",
    "license",
    "licence",
    "vat",
    "bank",
    "onboard",
    "onboarding",
    "supplier",
    "registration",
    "document",
    "lookup",
)
_UNRELATED_TOPIC_HINTS = (
    "leave policy",
    "who won",
    "world cup",
    "weather",
    "joke",
    "how are you",
    "who are you",
    "what can you do",
    "time is it",
    "current time",
)
_TRADE_DETAILS_HINTS = (
    "trade license details",
    "trade license detail",
    "trade details",
    "license details",
    "licence details",
    "my trade license",
    "my trade licence",
    "my license details",
    "my licence details",
    "trade document details",
    "license number",
    "licence number",
    "what are my trade details",
    "what are my trade license details",
    "show trade details",
    "show my trade license",
    "show me trade details",
    "give me trade details",
)


def _missing_configuration_response(name: str):
    return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}, status_code=500)


def _validate_body(body: dict):
    activity = body.get("activity")
    if activity is not None and not isinstance(activity, dict):
        return "bad_request", "'activity' must be a JSON object"
    input_text = _body_text(body)
    if activity is None and not input_text:
        return "bad_request", "Provide JSON with 'input', 'text', or 'activity'"
    return "", ""


def _tbms_response_has_results(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return False
    data = payload.get("data")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return len(results) > 0
        if isinstance(results, dict):
            return bool(results)
        return bool(data)
    if isinstance(data, list):
        return len(data) > 0
    return bool(data)


def _lookup_clarification_response() -> dict:
    return _json_response(
        _attach_structured_context(
            _with_response_metadata(
                {
                    "ok": True,
                    "status": "needs_clarification",
                    "response_type": "lookup_clarification",
                    "text": "Please provide the company/vendor name or trade license number.",
                },
                "backend",
            ),
            "Please provide the company/vendor name or trade license number.",
            source="backend",
            conversation_id=None,
            context_mode="lookup",
            reuse_memory=False,
        ),
        status_code=200,
    )


def _trade_details_request_response(conversation_id: Optional[str], text: str) -> Optional[func.HttpResponse]:
    if not conversation_id or not _looks_like_trade_details_request(text):
        return None
    trusted_trade_document = get_trusted_trade_document(conversation_id)
    if not trusted_trade_document:
        return None
    payload = _trusted_trade_document_response(trusted_trade_document, conversation_id)
    return _json_response(payload, status_code=200)


def _looks_like_trade_details_request(text: str) -> bool:
    normalized_text = _normalize_text(text).lower()
    if not normalized_text:
        return False
    if any(hint in normalized_text for hint in _TRADE_DETAILS_HINTS):
        return True
    has_trade = "trade" in normalized_text or "licen" in normalized_text
    has_details = "detail" in normalized_text or "number" in normalized_text or "expiry" in normalized_text or "activity" in normalized_text
    if has_trade and has_details:
        return True
    if "what" in normalized_text and "my" in normalized_text and has_trade:
        return True
    return False


def _trusted_trade_document_response(trusted_trade_document: dict, conversation_id: Optional[str]) -> dict:
    company_name = _trusted_trade_company_name(trusted_trade_document)
    trade_license_number = _trusted_trade_license_number(trusted_trade_document)
    expiry_date = _trusted_trade_expiry_date(trusted_trade_document)
    licensed_activities = _trusted_trade_activities(trusted_trade_document)
    text_parts = []
    if company_name:
        text_parts.append(f"Verified trade license details for {company_name}:")
    else:
        text_parts.append("Verified trade license details:")
    if trade_license_number:
        text_parts.append(f"- Trade license number: {trade_license_number}")
    if expiry_date:
        text_parts.append(f"- Expiry date: {expiry_date}")
    if licensed_activities:
        text_parts.append(f"- Licensed activities: {licensed_activities}")
    if not trade_license_number and not expiry_date and not licensed_activities:
        text_parts.append("No verified trade details were stored for this conversation.")
    payload = {
        "ok": True,
        "status": "completed",
        "response_type": "trusted_trade_document",
        "text": "\n".join(text_parts),
        "conversation_id": conversation_id,
        "context": {
            "intent": "lookup",
            "document_type": "trade",
            "entities": {
                "company_name": company_name,
                "trade_license_number": trade_license_number,
            },
            "next_action": "general_chat",
            "classification": {
                "label": "trade_document_details",
                "confidence": 0.99,
                "reason": "Trusted approved trade document found for this conversation.",
            },
        },
        "trade_document": trusted_trade_document,
    }
    return _with_response_metadata(payload, "backend")


def _trusted_trade_company_name(trusted_trade_document: dict) -> str:
    for key in ("company_name",):
        value = _normalize_text(trusted_trade_document.get(key))
        if value:
            return value
    company_match = trusted_trade_document.get("company_match") if isinstance(trusted_trade_document.get("company_match"), dict) else {}
    for key in ("matched_company_name", "requested_company_name"):
        value = _normalize_text(company_match.get(key))
        if value:
            return value
    results = trusted_trade_document.get("results") if isinstance(trusted_trade_document.get("results"), dict) else {}
    return _first_company_name(results, ["TradeName", "CompanyName", "TradeNameEnglish", "OperatingName", "BusinessName"])


def _trusted_trade_license_number(trusted_trade_document: dict) -> str:
    value = _normalize_text(trusted_trade_document.get("trade_license_number"))
    if value:
        return value
    results = trusted_trade_document.get("results") if isinstance(trusted_trade_document.get("results"), dict) else {}
    for field_name in ("LicenseNo", "LicenceNumber", "LicenseNumber", "LicenceNo", "UnifiedLicenceNo", "UnifiedRegistrationNo"):
        field_result = results.get(field_name)
        if isinstance(field_result, dict):
            candidate = _normalize_text(field_result.get("value"))
            if candidate:
                return candidate
    return ""


def _trusted_trade_expiry_date(trusted_trade_document: dict) -> str:
    value = _normalize_text(trusted_trade_document.get("expiry_date"))
    if value:
        return value
    acceptance = trusted_trade_document.get("document_acceptance") if isinstance(trusted_trade_document.get("document_acceptance"), dict) else {}
    return _normalize_text(acceptance.get("expiry_date"))


def _trusted_trade_activities(trusted_trade_document: dict) -> str:
    value = _normalize_text(trusted_trade_document.get("licensed_activities"))
    if value:
        return value
    results = trusted_trade_document.get("results") if isinstance(trusted_trade_document.get("results"), dict) else {}
    for field_name in ("LicenceActivities", "LicenseActivities"):
        field_result = results.get(field_name)
        if isinstance(field_result, dict):
            candidate = _normalize_text(field_result.get("value"))
            if candidate:
                return candidate
    return ""


def _tbms_http_response_to_payload(response) -> dict:
    body = None
    body_type = None
    try:
        if hasattr(response, "get_body"):
            body = response.get_body()
        elif hasattr(response, "body"):
            body = response.body
        elif hasattr(response, "text"):
            body = response.text
        body_type = type(body).__name__ if body is not None else None
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str) and body.strip():
            return json.loads(body)
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return {
        "ok": False,
        "error": {
            "code": "response_parse_error",
            "message": "Failed to parse TBMS response",
            "body_type": body_type,
            "raw_body": body if isinstance(body, str) else None,
            "status_code": getattr(response, "status_code", None),
        },
    }


def _annotate_source(payload: dict, source: str) -> dict:
    return _with_response_metadata(payload, source)


def _extract_json_payload(text: object) -> dict:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return {}
    candidates = [normalized_text]
    match = re.search(r"\{.*\}", normalized_text, re.DOTALL)
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


def _coerce_structured_response(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    parsed_payload = _extract_json_payload(payload.get("text"))
    if not parsed_payload:
        return payload
    combined = dict(payload)
    for key, value in parsed_payload.items():
        if key == "context" and isinstance(value, dict):
            existing_context = combined.get("context") if isinstance(combined.get("context"), dict) else {}
            merged_context = dict(existing_context)
            merged_context.update(value)
            entities = merged_context.get("entities") if isinstance(merged_context.get("entities"), dict) else {}
            if "company_name" in entities:
                entities["company_name"] = _normalize_company_name(entities.get("company_name"))
            merged_context["entities"] = entities
            combined["context"] = merged_context
        else:
            combined[key] = value
    return combined


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_company_name(value: object) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    trailing_suffixes = (
        "trading",
        "llc",
        "l.l.c",
        "co.",
        "co",
        "company",
        "corporation",
        "corp.",
        "corp",
        "branch",
        "establishment",
        "sole proprietorship",
    )
    while True:
        updated = normalized
        for suffix in trailing_suffixes:
            updated = re.sub(rf"(?:\s+|[\s,.-]+){re.escape(suffix)}$", "", updated, flags=re.IGNORECASE).strip(" ,.-")
        updated = _normalize_text(updated)
        if updated == normalized:
            break
        normalized = updated
    return normalized


def _general_bot_prompt(
    text: str,
    remembered_entities: Optional[dict[str, str]] = None,
    conversation_id: Optional[str] = None,
    context_mode: str = "chat",
) -> str:
    prompt_parts = [GENERAL_BOT_SYSTEM_PROMPT]
    context_lines: list[str] = []
    remembered_company = _normalize_text((remembered_entities or {}).get("company_name"))
    remembered_license = _normalize_text((remembered_entities or {}).get("trade_license_number"))
    if conversation_id:
        context_lines.append(f"conversation_id: {conversation_id}")
    if context_mode:
        context_lines.append(f"context_mode: {context_mode}")
    if remembered_company:
        context_lines.append(f"remembered_company_name: {remembered_company}")
    if remembered_license:
        context_lines.append(f"remembered_trade_license_number: {remembered_license}")
    if context_lines:
        prompt_parts.append(
            "Conversation context:\n"
            + "\n".join(f"- {line}" for line in context_lines)
            + "\nUse the conversation context only as a continuity hint. Do not invent values. If the user message conflicts with remembered context, prefer the current user message."
        )
    prompt_parts.append(f"User message:\n{text.strip()}")
    return "\n\n".join(prompt_parts)


def _default_structured_context() -> dict:
    return {
        "context_mode": "chat",
        "intent": "chat",
        "document_type": "unknown",
        "entities": {
            "company_name": "",
            "trade_license_number": "",
        },
        "next_action": "general_chat",
        "classification": {
            "label": "unknown",
            "confidence": 0.0,
            "reason": "General chat.",
        },
    }


def _normalize_context_mode(value: object) -> str:
    normalized = _normalize_text(value).lower().replace("-", "_")
    if normalized in {"general_chat", "chat", "general"}:
        return "chat"
    if normalized in {"lookup_request", "tbms", "tbms_lookup"}:
        return "lookup"
    if normalized in {"doc", "document", "document_review"}:
        return "document_review"
    if normalized == "workflow":
        return "workflow"
    if normalized in {"fresh", "continue", "lookup", "document_review", "chat"}:
        return normalized
    return ""


def _resolve_context_mode(body: dict, payload: Optional[dict] = None) -> str:
    for candidate in (
        body.get("context_mode"),
        body.get("contextMode"),
        body.get("reset_context") and "fresh",
        body.get("intent"),
    ):
        mode = _normalize_context_mode(candidate)
        if mode:
            if mode == "general_chat":
                return "chat"
            return mode
    if isinstance(payload, dict):
        payload_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        for candidate in (
            payload_context.get("context_mode"),
            payload_context.get("next_action"),
            payload_context.get("intent"),
        ):
            mode = _normalize_context_mode(candidate)
            if mode:
                return mode
    return "chat"


def _reuse_memory_for_context_mode(context_mode: str) -> bool:
    return context_mode in {"continue", "lookup"}


def _looks_like_topic_shift(text: str, remembered: dict[str, str]) -> bool:
    normalized_text = _normalize_text(text).lower()
    if not normalized_text:
        return False
    if any(value and value.lower() in normalized_text for value in remembered.values()):
        return False
    if any(hint in normalized_text for hint in _SUPPLIER_TOPIC_HINTS):
        return False
    if any(hint in normalized_text for hint in _UNRELATED_TOPIC_HINTS):
        return True
    words = [word for word in normalized_text.split() if word]
    if len(words) <= 4 and not any(char.isdigit() for char in normalized_text):
        return True
    return False


def _infer_response_context_mode(payload: Optional[dict], source: str, requested_context_mode: str) -> str:
    if requested_context_mode == "fresh":
        return "fresh"
    if source in {"tbms", "workflow", "backend"}:
        return "lookup"
    if isinstance(payload, dict):
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        for candidate in (
            context.get("context_mode"),
            context.get("next_action"),
            context.get("intent"),
        ):
            mode = _normalize_context_mode(candidate)
            if mode in {"lookup", "document_review", "chat", "workflow"}:
                return "lookup" if mode == "workflow" else mode
    return requested_context_mode if requested_context_mode in {"continue", "lookup", "document_review", "chat"} else "chat"


def _extract_tbms_company_name(results: object) -> str:
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            for key in ("vendorName", "vendName", "companyName", "company_name", "tradeName", "trade_name"):
                value = _normalize_text(item.get(key))
                if value:
                    return _normalize_company_name(value)
        return ""
    if isinstance(results, dict):
        for key in ("vendorName", "vendName", "companyName", "company_name", "tradeName", "trade_name"):
            value = _normalize_text(results.get(key))
            if value:
                return _normalize_company_name(value)
    return ""


def _extract_tbms_license_number(results: object) -> str:
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            for key in ("licenseNo", "license_no", "vendId", "vendorId"):
                value = _normalize_text(item.get(key))
                if value:
                    return value
        return ""
    if isinstance(results, dict):
        for key in ("licenseNo", "license_no", "vendId", "vendorId"):
            value = _normalize_text(results.get(key))
            if value:
                return value
    return ""


def _extract_tbms_company_candidates(results: object) -> list[str]:
    candidates: list[str] = []
    keys = ("vendorName", "vendName", "companyName", "company_name", "tradeName", "trade_name")
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            for key in keys:
                value = _normalize_text(item.get(key))
                if value and value not in candidates:
                    candidates.append(value)
    elif isinstance(results, dict):
        for key in keys:
            value = _normalize_text(results.get(key))
            if value and value not in candidates:
                candidates.append(value)
    return candidates


def _attach_lookup_match_details(payload: dict, decision: dict) -> dict:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    requested_company = _normalize_text(decision.get("vendor_name"))
    requested_license = _normalize_text(decision.get("license_no"))
    if not requested_company:
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    results = data.get("results")
    candidates = _extract_tbms_company_candidates(results)
    if not candidates:
        return payload
    best_match = None
    for candidate in candidates:
        comparison = compare_company_names(requested_company, candidate)
        if best_match is None or comparison.similarity_percent > best_match["similarity_percent"]:
            best_match = {
                "requested_company_name": requested_company,
                "requested_company_name_normalized": _canonical_company_name(requested_company),
                "requested_trade_license_number": requested_license,
                "matched_company_name": comparison.string2,
                "matched_company_name_normalized": comparison.normalized2,
                "exact_match": comparison.exact_match,
                "similarity_percent": comparison.similarity_percent,
            }
    if best_match is None:
        return payload
    best_match["match_status"] = "exact" if best_match["exact_match"] else ("close" if best_match["similarity_percent"] >= 80 else "mismatch")
    payload["lookup_match"] = best_match
    payload["context"] = context if context else payload.get("context", {})
    if best_match["match_status"] != "mismatch" and not entities.get("company_name") and best_match["matched_company_name_normalized"]:
        entities["company_name"] = best_match["matched_company_name_normalized"]
        context["entities"] = entities
        payload["context"] = context
    return payload


def _build_structured_context(
    text: str,
    payload: Optional[dict] = None,
    source: str = "llm",
    conversation_id: Optional[str] = None,
    reuse_memory: bool = True,
    context_mode: str = "chat",
) -> dict:
    normalized_text = _normalize_text(text)
    context = {}
    explicit_lookup_entities = bool(payload.get("_explicit_lookup_entities")) if isinstance(payload, dict) else False
    if isinstance(payload, dict):
        raw_context = payload.get("context")
        if isinstance(raw_context, dict):
            context = dict(raw_context)
        else:
            parsed_payload = _extract_json_payload(payload.get("text"))
            parsed_context = parsed_payload.get("context") if isinstance(parsed_payload.get("context"), dict) else {}
            if isinstance(parsed_context, dict):
                context = dict(parsed_context)
            elif isinstance(parsed_payload, dict) and parsed_payload:
                context = dict(parsed_payload.get("context") or {})

    default_context = _default_structured_context()
    merged_context = dict(default_context)
    merged_context["context_mode"] = context_mode or default_context["context_mode"]
    if isinstance(context, dict) and context:
        merged_context.update({key: value for key, value in context.items() if key != "entities" and key != "classification"})
        entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
        if "company_name" in entities:
            entities["company_name"] = _normalize_company_name(entities.get("company_name"))
        merged_context["entities"] = {
            **default_context["entities"],
            **{key: value for key, value in entities.items() if key in default_context["entities"]},
        }
        classification = context.get("classification") if isinstance(context.get("classification"), dict) else {}
        merged_context["classification"] = {
            **default_context["classification"],
            **classification,
        }
    else:
        merged_context.update(
            {
                "intent": default_context["intent"],
                "document_type": default_context["document_type"],
                "next_action": default_context["next_action"],
                "classification": default_context["classification"],
            }
        )
        if source == "tbms" and isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            results = data.get("results") if isinstance(data.get("results"), (list, dict)) else None
            company_name = _extract_tbms_company_name(results)
            trade_license_number = _extract_tbms_license_number(results)
            merged_context["entities"] = {
                "company_name": company_name,
                "trade_license_number": trade_license_number,
            }
        if reuse_memory:
            remembered = get_conversation_entities(conversation_id)
            entities = merged_context.get("entities") if isinstance(merged_context.get("entities"), dict) else {}
            if not entities.get("company_name"):
                entities["company_name"] = remembered.get("company_name", "")
            if not entities.get("trade_license_number"):
                entities["trade_license_number"] = remembered.get("trade_license_number", "")
            merged_context["entities"] = entities
    if source == "backend":
        merged_context["intent"] = "lookup"
        merged_context["next_action"] = "ask_clarification"
    elif source == "workflow":
        merged_context["intent"] = "lookup"
        merged_context["next_action"] = "workflow"
    elif source == "tbms":
        merged_context["intent"] = "lookup"
        merged_context["next_action"] = "tbms_lookup"
    entities = merged_context.get("entities") if isinstance(merged_context.get("entities"), dict) else {}
    if source == "llm" and explicit_lookup_entities:
        merged_context["intent"] = "lookup"
        merged_context["next_action"] = "tbms_lookup"
    return merged_context


def _attach_structured_context(
    payload: dict,
    text: str,
    source: str = "llm",
    conversation_id: Optional[str] = None,
    context_mode: Optional[str] = None,
    reuse_memory: Optional[bool] = None,
) -> dict:
    combined = dict(payload)
    resolved_context_mode = context_mode or _infer_response_context_mode(combined, source, "chat")
    if reuse_memory is None:
        reuse_memory = _reuse_memory_for_context_mode(resolved_context_mode)
    context = _build_structured_context(
        text,
        payload,
        source=source,
        conversation_id=conversation_id,
        reuse_memory=reuse_memory,
        context_mode=resolved_context_mode,
    )
    combined["context"] = context
    return combined


def _apply_lookup_decision_context(payload: dict, decision: dict) -> dict:
    combined = dict(payload)
    context = combined.get("context") if isinstance(combined.get("context"), dict) else _default_structured_context()
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    if decision.get("lookup_type") == "company_name" and not entities.get("company_name"):
        entities["company_name"] = _normalize_company_name(decision.get("vendor_name"))
    if decision.get("lookup_type") == "trade_license_number" and not entities.get("trade_license_number"):
        entities["trade_license_number"] = _normalize_text(decision.get("license_no"))
    if decision.get("route") == "tbms":
        if not entities.get("company_name"):
            entities["company_name"] = _normalize_company_name(decision.get("vendor_name"))
        if not entities.get("trade_license_number"):
            entities["trade_license_number"] = _normalize_text(decision.get("license_no"))
        if context.get("intent") == "chat":
            context["intent"] = "lookup"
        if context.get("next_action") in {"general_chat", "document_review"}:
            context["next_action"] = "tbms_lookup"
    context["entities"] = entities
    combined["context"] = context
    return combined


async def _lookup_response(text: str, config: dict, conversation_id: Optional[str] = None):
    if not enable_tbms_lookup():
        return None
    decision = await classify_lookup_route(text, config)
    if decision.get("route") == "clarify":
        return _lookup_clarification_response()
    payloads = build_lookup_payloads(decision)
    if not payloads:
        if decision.get("route") == "tbms":
            return _lookup_clarification_response()
        return None
    last_payload = None
    last_response = None
    for payload in payloads:
        last_payload = payload
        tbms_response = await asyncio.to_thread(_call_tbms_api, "GetVendorList", payload, None)
        last_response = tbms_response
        response_payload = _tbms_http_response_to_payload(tbms_response)
        if tbms_response.status_code < 400 and _tbms_response_has_results(response_payload):
            payload = _attach_structured_context(
                _annotate_source(response_payload, "tbms"),
                text,
                source="tbms",
                conversation_id=conversation_id,
                context_mode="lookup",
                reuse_memory=True,
            )
            payload = _apply_lookup_decision_context(payload, decision)
            payload = _attach_lookup_match_details(payload, decision)
            context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
            remember_conversation_entities(conversation_id, entities.get("company_name", ""), entities.get("trade_license_number", ""))
            return _json_response(payload, status_code=tbms_response.status_code)
    if last_response is None:
        return None
    fallback_payload = _tbms_http_response_to_payload(last_response)
    if isinstance(fallback_payload, dict):
        fallback_payload.setdefault("lookup_attempt", last_payload)
    payload = _attach_structured_context(
        _annotate_source(fallback_payload, "tbms"),
        text,
        source="tbms",
        conversation_id=conversation_id,
        context_mode="lookup",
        reuse_memory=True,
    )
    payload = _apply_lookup_decision_context(payload, decision)
    payload = _attach_lookup_match_details(payload, decision)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    remember_conversation_entities(conversation_id, entities.get("company_name", ""), entities.get("trade_license_number", ""))
    return _json_response(payload, status_code=last_response.status_code)


def _resolve_config():
    project_endpoint = foundry_project_endpoint()
    agent_id = general_bot_agent_id()
    token_scope = foundry_token_scope()
    if not project_endpoint:
        return None, _missing_configuration_response("FOUNDRY_PROJECT_ENDPOINT")
    if not agent_id:
        return None, _missing_configuration_response("GENERAL_BOT_AGENT_ID")
    return {"project_endpoint": project_endpoint, "agent_id": agent_id, "token_scope": token_scope}, None


def _invoke_general_bot_workflow(body: dict, config: dict, remembered_entities: Optional[dict[str, str]] = None, context_mode: str = "chat"):
    return asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=_general_bot_prompt(
                _body_text(body),
                remembered_entities=remembered_entities,
                conversation_id=_conversation_id(body),
                context_mode=context_mode,
            ),
            conversation_id=_conversation_id(body),
            include=body.get("include") if isinstance(body.get("include"), list) else None,
            previous_response_id=body.get("previous_response_id") if isinstance(body.get("previous_response_id"), str) and body.get("previous_response_id").strip() else None,
            stream=None,
            project_endpoint=config["project_endpoint"],
            agent_id=config["agent_id"],
            token_scope=config["token_scope"],
        )
    )


def _user_id(body: dict) -> str:
    if isinstance(body.get("user_id"), str) and body["user_id"].strip():
        return body["user_id"].strip()
    activity = body.get("activity")
    if isinstance(activity, dict):
        sender = activity.get("from")
        if isinstance(sender, dict) and isinstance(sender.get("id"), str):
            return sender["id"].strip()
    return "web-user"


def _workflow_result(workflow_url: str, body: dict) -> tuple[int, dict]:
    return invoke_activity_workflow(workflow_url, _body_text(body), _conversation_id(body), _user_id(body))


def _route_trade_license(payload: dict, body: dict) -> tuple[int, dict]:
    route = classify_trade_license_routing(payload.get("text") or "")
    return (200, payload) if route is None else _route_trade_license_payload(payload, body, route)


def _route_trade_license_payload(payload: dict, body: dict, route) -> tuple[int, dict]:
    workflow_status, workflow_payload = _workflow_result(route.workflow_url, body)
    return 200, _trade_license_payload(payload, route, workflow_status, workflow_payload)


def _trade_license_payload(payload: dict, route, workflow_status: int, workflow_payload: dict) -> dict:
    combined = dict(payload)
    combined["routing"] = _trade_license_routing(route)
    combined["workflow_started"] = workflow_status < 400
    combined["workflow_response"] = workflow_payload
    combined["text"] = route.message
    return _trade_license_outcome(_with_response_metadata(combined, "workflow"), route)


def _trade_license_routing(route) -> dict:
    return {
        "expiry_date": route.decision.expiry_date.isoformat(),
        "days_remaining": route.decision.days_remaining,
        "status": route.decision.status,
        "workflow_name": route.workflow_name,
    }


def _trade_license_outcome(combined: dict, route) -> dict:
    if route.decision.status == "expired":
        combined["ok"] = False
        combined["status"] = "expired"
        combined["error"] = {"code": "trade_license_expired", "message": route.message}
        return combined
    combined["status"] = "renewal_due"
    combined["warning"] = {"code": "trade_license_renewal_due", "message": route.message}
    return combined


async def invoke_general_bot(req: Request):
    body = await _json_body(req)
    error_code, error_message = _validate_body(body)
    if error_code:
        return _json_response({"ok": False, "error": {"code": error_code, "message": error_message}}, status_code=400)
    config, config_error = _resolve_config()
    if config_error is not None:
        return config_error
    conversation_id = _conversation_id(body)
    remembered_entities = get_conversation_entities(conversation_id)
    requested_context_mode = _resolve_context_mode(body)
    if requested_context_mode == "fresh":
        clear_conversation_entities(conversation_id)
        clear_trusted_trade_document(conversation_id)
        remembered_entities = {"company_name": "", "trade_license_number": ""}
    elif requested_context_mode in {"", "chat"} and _looks_like_topic_shift(_body_text(body), remembered_entities):
        clear_conversation_entities(conversation_id)
        remembered_entities = {"company_name": "", "trade_license_number": ""}
    trade_details_response = _trade_details_request_response(conversation_id, _body_text(body))
    if trade_details_response is not None:
        return trade_details_response
    lookup_response = await _lookup_response(_body_text(body), config, conversation_id=conversation_id)
    if lookup_response is not None:
        return lookup_response
    status_code, payload = await _invoke_general_bot_workflow(body, config, remembered_entities=remembered_entities, context_mode=requested_context_mode)
    llm_response = deepcopy(payload) if isinstance(payload, dict) else {}
    payload = _coerce_structured_response(payload)
    llm_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    llm_entities = llm_context.get("entities") if isinstance(llm_context.get("entities"), dict) else {}
    payload["_explicit_lookup_entities"] = bool(llm_entities.get("company_name") or llm_entities.get("trade_license_number"))
    payload = _annotate_source(payload, "llm")
    payload = _attach_structured_context(
        payload,
        _body_text(body),
        source="llm",
        conversation_id=conversation_id,
        context_mode=requested_context_mode,
        reuse_memory=_reuse_memory_for_context_mode(requested_context_mode),
    )
    status_code, payload = _route_trade_license(payload, body)
    response_context_mode = _infer_response_context_mode(payload, payload.get("source", "llm"), requested_context_mode)
    payload = _attach_structured_context(
        payload,
        _body_text(body),
        source="workflow" if payload.get("source") == "workflow" else payload.get("source", "llm"),
        conversation_id=conversation_id,
        context_mode=response_context_mode,
        reuse_memory=_reuse_memory_for_context_mode(response_context_mode),
    )
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    remember_conversation_entities(conversation_id, entities.get("company_name", ""), entities.get("trade_license_number", ""))
    if isinstance(payload, dict):
        payload.pop("_explicit_lookup_entities", None)
    if isinstance(payload, dict) and "source" not in payload:
        payload["source"] = "llm"
    if llm_response:
        payload["llm_response"] = llm_response
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
