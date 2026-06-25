from __future__ import annotations

import re
from typing import Any

from app.core.config import lookup_business_only_hints, lookup_classification_prompt, lookup_company_hints


LICENSE_PATTERN = re.compile(r"^(?:[a-z]{1,5}-)?\d{3,}(?:\s+\d{3,})*$", re.IGNORECASE)
ALPHANUMERIC_LICENSE_PATTERN = re.compile(r"^(?:[a-z]{1,5}-)?[a-z0-9]+(?:[-/][a-z0-9]+)+$", re.IGNORECASE)
COMPANY_LABEL_PATTERN = re.compile(r"\b(?:vendor\s*name|company\s*name|company|vendor|business\s*name|trade\s*name|legal\s*name)\b", re.IGNORECASE)
LICENSE_LABEL_PATTERN = re.compile(r"\b(?:trade\s*)?(?:licen[cs]e|licence)(?:\s*(?:no\.?|number))?\b", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _looks_like_company(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in lookup_company_hints())


def _looks_like_license(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(LICENSE_PATTERN.fullmatch(text)) or bool(ALPHANUMERIC_LICENSE_PATTERN.fullmatch(compact))


def _looks_like_person(text: str) -> bool:
    lowered = text.lower()
    if not text or _looks_like_company(text) or _looks_like_license(text):
        return False
    if any(hint in lowered for hint in BUSINESS_ONLY_HINTS):
        return False
    if any(char.isdigit() for char in text):
        return False
    words = [word for word in re.split(r"\s+", text) if word]
    if len(words) < 2:
        return False
    return len(words) <= 5


def _has_company_label(text: str) -> bool:
    return bool(COMPANY_LABEL_PATTERN.search(text or ""))


def _has_license_label(text: str) -> bool:
    return bool(LICENSE_LABEL_PATTERN.search(text or ""))


def classify_lookup_input(text: Any) -> dict[str, Any]:
    _ = lookup_classification_prompt()
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return {"label": "unknown", "confidence": 0.0, "reason": "Empty input."}
    if _has_company_label(normalized_text):
        return {"label": "company_name", "confidence": 0.98, "reason": "Contains an explicit company/vendor label."}
    if _has_license_label(normalized_text):
        return {"label": "trade_license_number", "confidence": 0.98, "reason": "Contains an explicit license label."}
    if _looks_like_license(normalized_text):
        return {"label": "trade_license_number", "confidence": 0.99, "reason": "Matches a license-like number pattern."}
    if _looks_like_company(normalized_text):
        return {"label": "company_name", "confidence": 0.98, "reason": "Contains company or business suffix keywords."}
    if any(hint in normalized_text.lower() for hint in lookup_business_only_hints()):
        return {"label": "unknown", "confidence": 0.55, "reason": "Looks like a business phrase but lacks a clear company suffix or label."}
    if _looks_like_person(normalized_text):
        return {"label": "person_name", "confidence": 0.9, "reason": "Looks like a personal name without company keywords."}
    if len(normalized_text.split()) >= 2 and not any(char.isdigit() for char in normalized_text):
        return {"label": "person_name", "confidence": 0.65, "reason": "Multiple words and no company keywords or numbers."}
    return {"label": "unknown", "confidence": 0.4, "reason": "Did not match company, person, or license patterns."}
