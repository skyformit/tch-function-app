import re
from typing import Any, Optional

from app.infrastructure.document_text_extraction import extract_bank_account_name_from_pdf, extract_tax_registration_number_from_pdf


def _collect_text_fragments(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"content", "text", "valueString", "value", "paragraph", "line"} and isinstance(item, str):
                fragments.append(item)
            fragments.extend(_collect_text_fragments(item))
    elif isinstance(value, list):
        for item in value:
            fragments.extend(_collect_text_fragments(item))
    return fragments


def _extract_tax_registration_number_from_analysis_payload(raw_result: Any) -> Optional[str]:
    fragments = _collect_text_fragments(raw_result)
    if not fragments:
        return None
    text = "\n".join(fragments)
    patterns = [r"Tax\s*Registration\s*Number\s*[:\-]?\s*([0-9]{15})", r"TaxRegistrationNumber\s*[:\-]?\s*([0-9]{15})", r"\b([0-9]{15})\b"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
    return None


def _apply_vat_pdf_fallback(response_payload: dict[str, Any], file_bytes: bytes) -> dict[str, Any]:
    results = response_payload.get("results")
    if not isinstance(results, dict):
        return response_payload
    existing_value = results.get("TaxRegistrationNumber", {}).get("value") if isinstance(results.get("TaxRegistrationNumber"), dict) else None
    if existing_value not in (None, "", [], {}):
        return response_payload
    fallback_value = extract_tax_registration_number_from_pdf(file_bytes)
    if not fallback_value:
        return response_payload
    results["TaxRegistrationNumber"] = {"value": fallback_value, "confidence": None}
    response_payload["results"] = results
    return _promote_status_if_needed(response_payload)


def _apply_vat_analysis_fallback(response_payload: dict[str, Any], file_bytes: bytes, content_type: Optional[str]) -> dict[str, Any]:
    results = response_payload.get("results")
    if not isinstance(results, dict):
        results = {}
    if _has_tax_registration_number(results):
        return response_payload
    fallback_value = extract_tax_registration_number_from_pdf(file_bytes)
    if not fallback_value:
        fallback_value = _fallback_from_document_intelligence(file_bytes, content_type)
    if not fallback_value:
        return response_payload
    results["TaxRegistrationNumber"] = {"value": fallback_value, "confidence": None}
    response_payload["results"] = results
    return _promote_status_if_needed(response_payload)


def _fallback_from_document_intelligence(file_bytes: bytes, content_type: Optional[str]) -> Optional[str]:
    from app.infrastructure.external.document_intelligence_client import analyze_document as analyze_with_document_intelligence

    try:
        raw_payload, _, _ = analyze_with_document_intelligence(file_bytes, content_type or "application/pdf", query_fields=[], model_id_override="prebuilt-read")
    except Exception:
        return None
    return _extract_tax_registration_number_from_analysis_payload(raw_payload)


def _has_tax_registration_number(results: dict) -> bool:
    existing = results.get("TaxRegistrationNumber")
    return isinstance(existing, dict) and existing.get("value") not in (None, "", [], {})


def _apply_bank_account_name_fallback(response_payload: dict[str, Any], file_bytes: bytes) -> dict[str, Any]:
    results = response_payload.get("results")
    if not isinstance(results, dict):
        results = {}
    existing = results.get("AccountName")
    if isinstance(existing, dict) and existing.get("value") not in (None, "", [], {}):
        return response_payload
    fallback_value = extract_bank_account_name_from_pdf(file_bytes)
    if not fallback_value:
        return response_payload
    results["AccountName"] = {"value": fallback_value, "confidence": None}
    response_payload["results"] = results
    return _promote_status_if_needed(response_payload)


def _promote_status_if_needed(response_payload: dict[str, Any]) -> dict[str, Any]:
    if response_payload.get("status") == "fail":
        response_payload["status"] = "success"
        response_payload.pop("error", None)
    return response_payload

