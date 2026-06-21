from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Optional

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover - dependency may be absent in some local envs
    AzureOpenAI = None

from app.core.document_settings import (
    document_review_openai_api_key,
    document_review_openai_api_version,
    document_review_openai_deployment_name,
    document_review_openai_endpoint,
    document_review_openai_system_prompt,
)
from app.infrastructure.document_qr_extraction import _extract_urls_from_text, extract_qr_codes_from_pdf, extract_verification_urls_from_pdf


def extract_qr_codes(json_data: Any) -> list[str]:
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    qr_values: list[str] = []
    _scan_qr_values(data, qr_values)
    return qr_values


def _scan_qr_values(value: Any, qr_values: list[str]) -> None:
    if isinstance(value, dict):
        _collect_qr_from_barcodes(value, qr_values)
        for item in value.values():
            _scan_qr_values(item, qr_values)
    elif isinstance(value, list):
        for item in value:
            _scan_qr_values(item, qr_values)


def _collect_qr_from_barcodes(value: dict, qr_values: list[str]) -> None:
    for barcode in value.get("barcodes", []):
        if not isinstance(barcode, dict):
            continue
        kind = str(barcode.get("kind") or "")
        decoded_value = barcode.get("value")
        if "qr" in kind.lower() and decoded_value and decoded_value not in qr_values:
            qr_values.append(decoded_value)


def build_qr_codes_result(raw_result: Any, file_bytes: bytes | None = None) -> dict[str, Any]:
    qr_codes = extract_qr_codes(raw_result)
    if not qr_codes and file_bytes:
        qr_codes = extract_qr_codes_from_pdf(file_bytes)
    return {"value": qr_codes or None, "confidence": 0.95 if qr_codes else 0.0}


def build_verification_urls_result(raw_result: Any | None = None, file_bytes: bytes | None = None) -> dict[str, Any]:
    urls = extract_verification_urls_from_pdf(file_bytes) if file_bytes else []
    if not urls and raw_result is not None:
        for payload in extract_qr_codes(raw_result):
            urls.extend(_extract_urls_from_text(payload))
    return {"value": urls or None, "confidence": 0.95 if urls else 0.0}


def review_with_azure_openai(extracted_fields: dict[str, Any], deployment_name: Optional[str] = None) -> dict[str, Any]:
    if AzureOpenAI is None:
        return _review_unavailable("openai package is not installed")
    try:
        client, deployment = _build_openai_client_and_deployment(deployment_name)
        if client is None or deployment is None:
            return _review_unavailable("Missing review configuration")
        raw_text = _review_text(client, extracted_fields, deployment)
        return _parse_review(raw_text)
    except Exception as exc:
        logging.error("Azure OpenAI review failed: %s", exc)
        return _review_failed(str(exc))


def extract_document_fields_with_azure_openai(raw_result: Any, today: Optional[date] = None, deployment_name: Optional[str] = None) -> dict[str, Any]:
    if AzureOpenAI is None:
        return _extraction_unavailable("openai package is not installed")
    try:
        client, deployment = _build_openai_client_and_deployment(deployment_name)
        if client is None or deployment is None:
            return _extraction_unavailable("Missing extraction configuration")
        resolved_today = today or date.today()
        raw_text = _extraction_text(client, raw_result, deployment, today=resolved_today)
        return _normalize_extraction(_parse_extraction(raw_text), resolved_today)
    except Exception as exc:
        logging.error("Azure OpenAI extraction failed: %s", exc)
        return _extraction_failed(str(exc))


def _build_openai_client_and_deployment(deployment_name: Optional[str] = None) -> tuple[Any | None, str | None]:
    endpoint = document_review_openai_endpoint()
    api_key = document_review_openai_api_key()
    deployment = (deployment_name or document_review_openai_deployment_name() or "").strip()
    if not endpoint or not deployment:
        return None, None
    client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=document_review_openai_api_version())
    return client, deployment


def _review_text(client: AzureOpenAI, extracted_fields: dict[str, Any], deployment: str) -> str:
    response = client.chat.completions.create(model=deployment, messages=_review_messages(extracted_fields), temperature=0, max_tokens=600)
    return (response.choices[0].message.content or "").strip()


def _review_messages(extracted_fields: dict[str, Any]) -> list[dict[str, str]]:
    return [{"role": "system", "content": _review_system_prompt()}, {"role": "user", "content": f"Extracted fields:\n{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}"}]


def _review_system_prompt() -> str:
    return document_review_openai_system_prompt()


def _parse_review(raw_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _review_failed(raw_text)


def _review_failed(reasoning: str) -> dict[str, Any]:
    return {"is_consistent": False, "anomalies": ["Could not parse GPT review output."], "plausibility_score": 0.0, "reasoning": reasoning}


def _review_unavailable(reasoning: str) -> dict[str, Any]:
    return {"is_consistent": False, "anomalies": [reasoning], "plausibility_score": 0.0, "reasoning": reasoning, "skipped": True}


def _extraction_text(client: AzureOpenAI, raw_result: Any, deployment: str, today: date) -> str:
    response = client.chat.completions.create(model=deployment, messages=_extraction_messages(raw_result, today), temperature=0, max_tokens=1200)
    return (response.choices[0].message.content or "").strip()


def _extraction_messages(raw_result: Any, today: date) -> list[dict[str, str]]:
    return [{"role": "system", "content": _extraction_system_prompt()}, {"role": "user", "content": f"Today: {today.isoformat()}\n\nRaw document analysis JSON:\n{json.dumps(raw_result, indent=2, ensure_ascii=False)}"}]


def _extraction_system_prompt() -> str:
    return (
        "You are a document extraction assistant.\n\n"
        "You will receive raw OCR / document analysis JSON from a PDF. Your job is to extract specific business and compliance fields exactly as they appear in the document.\n\n"
        "Rules:\n"
        "- Extract only fields that are explicitly present in the input.\n"
        "- Do NOT guess, infer, or invent values.\n"
        "- Do NOT merge unrelated values.\n"
        "- Do NOT use external knowledge.\n"
        "- Preserve the original value as closely as possible.\n"
        "- Normalize whitespace.\n"
        "- For dates, return ISO format YYYY-MM-DD when possible.\n"
        "- If a field is missing or unclear, return null for its value.\n"
        "- If multiple values exist for the same field, prefer the clearest exact value from the document.\n"
        "- If the document contains both Arabic and English, extract the English value when available for English-name fields.\n"
        "- Compute is_expired only when both expiry_date and today are available.\n"
        "- is_expired should be true only when expiry_date is earlier than today.\n"
        "- If the document type is not obvious, set document_type to \"unknown\".\n\n"
        "If the document is a trade license:\n"
        "- extract trade_license_number, expiry_date, company_name, license_activities, issue_date, official_email, official_mobile, qr_codes, verification_urls\n\n"
        "If the document is a VAT document:\n"
        "- extract vat_number, company_name, issue_date, official_email if present\n\n"
        "If the document is a bank letter:\n"
        "- extract bank_name, account_number, iban, account_holder/company_name, official_email if present\n\n"
        "Return ONLY valid JSON. No markdown. No explanation.\n"
        "Use this exact output schema:\n"
        "{\n"
        '  "document_type": "trade|bank|vat|unknown",\n'
        '  "trade_license_number": {"value": null, "confidence": null},\n'
        '  "expiry_date": {"value": null, "confidence": null},\n'
        '  "is_expired": {"value": null, "confidence": null},\n'
        '  "company_name": {"value": null, "confidence": null},\n'
        '  "bank_name": {"value": null, "confidence": null},\n'
        '  "account_number": {"value": null, "confidence": null},\n'
        '  "iban": {"value": null, "confidence": null},\n'
        '  "vat_number": {"value": null, "confidence": null},\n'
        '  "license_activities": {"value": null, "confidence": null},\n'
        '  "issue_date": {"value": null, "confidence": null},\n'
        '  "official_email": {"value": null, "confidence": null},\n'
        '  "official_mobile": {"value": null, "confidence": null},\n'
        '  "qr_codes": {"value": [], "confidence": null},\n'
        '  "verification_urls": {"value": [], "confidence": null}\n'
        "}"
    )


def _parse_extraction(raw_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _extraction_failed(raw_text)


def _normalize_extraction(extraction: dict[str, Any], today: date) -> dict[str, Any]:
    if not isinstance(extraction, dict):
        return extraction
    normalized = dict(extraction)
    expiry_entry = normalized.get("expiry_date")
    is_expired_entry = normalized.get("is_expired")
    if not isinstance(expiry_entry, dict):
        return normalized
    expiry_value = expiry_entry.get("value")
    if expiry_value in (None, "", [], {}):
        if isinstance(is_expired_entry, dict):
            is_expired_entry["value"] = None
            is_expired_entry["confidence"] = 0.0
            normalized["is_expired"] = is_expired_entry
        return normalized
    from app.use_cases.trade_license_expiry import parse_trade_license_expiry_date

    parsed_expiry = parse_trade_license_expiry_date(expiry_value)
    if isinstance(is_expired_entry, dict):
        is_expired_entry["value"] = bool(parsed_expiry and parsed_expiry < today)
        is_expired_entry["confidence"] = 1.0 if parsed_expiry is not None else 0.0
        normalized["is_expired"] = is_expired_entry
    return normalized


def _extraction_failed(reasoning: str) -> dict[str, Any]:
    return {"document_type": "unknown", "anomalies": ["Could not parse extraction output."], "reasoning": reasoning, "skipped": True}


def _extraction_unavailable(reasoning: str) -> dict[str, Any]:
    return {"document_type": "unknown", "anomalies": [reasoning], "reasoning": reasoning, "skipped": True}


def build_trade_license_extras(raw_result: Any, extracted_fields: dict[str, Any], file_bytes: bytes | None = None) -> dict[str, Any]:
    extras = {
        "qr_codes": build_qr_codes_result(raw_result, file_bytes),
        "verification_urls": build_verification_urls_result(raw_result, file_bytes),
    }
    gpt_review = review_with_azure_openai(extracted_fields)
    extras["gpt_review"] = gpt_review
    extras["llm_extraction"] = extract_document_fields_with_azure_openai(raw_result)
    return extras
