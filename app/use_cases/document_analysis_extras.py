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
    document_analysis_combined_openai_system_prompt,
    document_analysis_extraction_openai_system_prompt,
    document_review_openai_api_key,
    document_review_openai_api_version,
    document_review_openai_deployment_name,
    document_review_openai_endpoint,
    document_review_openai_max_tokens,
    document_review_openai_min_tokens,
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
    qr_codes = _extract_qr_payloads(raw_result, file_bytes)
    return {"value": qr_codes or None, "confidence": 0.95 if qr_codes else 0.0}


def build_qr_payloads_result(raw_result: Any, file_bytes: bytes | None = None) -> dict[str, Any]:
    qr_payloads = _extract_qr_payloads(raw_result, file_bytes)
    return {"value": qr_payloads or None, "confidence": 0.95 if qr_payloads else 0.0}


def build_verification_urls_result(raw_result: Any | None = None, file_bytes: bytes | None = None) -> dict[str, Any]:
    urls = extract_verification_urls_from_pdf(file_bytes) if file_bytes else []
    if not urls and raw_result is not None:
        for payload in extract_qr_codes(raw_result):
            extracted_urls = _extract_urls_from_text(payload)
            if extracted_urls:
                urls.extend(extracted_urls)
            else:
                cleaned_payload = str(payload or "").strip()
                if cleaned_payload:
                    urls.append(cleaned_payload)
    if not urls and file_bytes:
        for payload in extract_qr_codes_from_pdf(file_bytes):
            extracted_urls = _extract_urls_from_text(payload)
            if extracted_urls:
                urls.extend(extracted_urls)
            else:
                cleaned_payload = str(payload or "").strip()
                if cleaned_payload:
                    urls.append(cleaned_payload)
    return {"value": urls or None, "confidence": 0.95 if urls else 0.0}


def _extract_qr_payloads(raw_result: Any | None = None, file_bytes: bytes | None = None) -> list[str]:
    payloads = extract_qr_codes(raw_result) if raw_result is not None else []
    if not payloads and file_bytes:
        payloads = extract_qr_codes_from_pdf(file_bytes)
    return payloads


def review_with_azure_openai(
    extracted_fields: dict[str, Any],
    deployment_name: Optional[str] = None,
    context_hint: Optional[str] = None,
) -> dict[str, Any]:
    if AzureOpenAI is None:
        return _review_unavailable("openai package is not installed")
    try:
        client, deployment = _build_openai_client_and_deployment(deployment_name)
        if client is None or deployment is None:
            return _review_unavailable("Missing review configuration")
        raw_text = _review_text(client, extracted_fields, deployment, context_hint=context_hint)
        return _parse_review(raw_text)
    except Exception as exc:
        logging.error("Azure OpenAI review failed: %s", exc)
        return _review_failed(str(exc))


def extract_document_fields_with_azure_openai(
    raw_result: Any,
    today: Optional[date] = None,
    deployment_name: Optional[str] = None,
    context_hint: Optional[str] = None,
) -> dict[str, Any]:
    if AzureOpenAI is None:
        return _extraction_unavailable("openai package is not installed")
    try:
        client, deployment = _build_openai_client_and_deployment(deployment_name)
        if client is None or deployment is None:
            return _extraction_unavailable("Missing extraction configuration")
        resolved_today = today or date.today()
        raw_text = _extraction_text(client, raw_result, deployment, today=resolved_today, context_hint=context_hint)
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


def _review_text(client: AzureOpenAI, extracted_fields: dict[str, Any], deployment: str, context_hint: Optional[str] = None) -> str:
    response = client.chat.completions.create(
        model=deployment,
        messages=_review_messages(extracted_fields, context_hint=context_hint),
        temperature=0,
        max_tokens=_review_max_tokens(),
    )
    return (response.choices[0].message.content or "").strip()


def _review_messages(extracted_fields: dict[str, Any], context_hint: Optional[str] = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _review_system_prompt()},
        {
            "role": "user",
            "content": (
                _document_context_block(context_hint)
                + f"Extracted fields:\n{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}"
            ),
        },
    ]


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


def _extraction_text(client: AzureOpenAI, raw_result: Any, deployment: str, today: date, context_hint: Optional[str] = None) -> str:
    response = client.chat.completions.create(
        model=deployment,
        messages=_extraction_messages(raw_result, today, context_hint=context_hint),
        temperature=0,
        max_tokens=_review_max_tokens(),
    )
    return (response.choices[0].message.content or "").strip()


def _extraction_messages(raw_result: Any, today: date, context_hint: Optional[str] = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _extraction_system_prompt()},
        {
            "role": "user",
            "content": (
                _document_context_block(context_hint)
                + f"Today: {today.isoformat()}\n\n"
                f"Raw document analysis content:\n{json.dumps(_raw_result_content_only(raw_result), indent=2, ensure_ascii=False)}"
            ),
        },
    ]


def _document_context_block(context_hint: Optional[str]) -> str:
    context_text = " ".join(str(context_hint or "").split()).strip()
    if not context_text:
        return ""
    return (
        "Conversation/document context (use only as continuity hints; do not invent values):\n"
        f"{context_text}\n\n"
    )


def _raw_result_content_only(raw_result: Any) -> Any:
    if isinstance(raw_result, dict):
        return raw_result.get("content") or ""
    return ""


def _extraction_system_prompt() -> str:
    return document_analysis_extraction_openai_system_prompt()

def _review_max_tokens() -> int:
    return max(document_review_openai_min_tokens(), document_review_openai_max_tokens())


def _combined_messages(raw_result: Any, extracted_fields: dict[str, Any], today: date, context_hint: Optional[str] = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _combined_system_prompt()},
        {
            "role": "user",
            "content": (
                _document_context_block(context_hint)
                + f"Today: {today.isoformat()}\n\n"
                f"Extracted fields:\n{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}\n\n"
                f"Raw document analysis content:\n{json.dumps(_raw_result_content_only(raw_result), indent=2, ensure_ascii=False)}"
            ),
        },
    ]


def _combined_system_prompt() -> str:
    return document_analysis_combined_openai_system_prompt()

def _parse_combined_output(raw_text: str, today: date) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "gpt_review": _review_failed(raw_text),
            "llm_extraction": _extraction_failed(raw_text),
        }
    gpt_review = parsed.get("gpt_review")
    llm_extraction = parsed.get("llm_extraction")
    return {
        "gpt_review": gpt_review if isinstance(gpt_review, dict) else _review_failed(raw_text),
        "llm_extraction": _normalize_extraction(llm_extraction if isinstance(llm_extraction, dict) else _extraction_failed(raw_text), today),
    }


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
    for field_name in (
        "trade_license_number",
        "expiry_date",
        "company_name",
        "issuing_authority",
        "bank_name",
        "account_number",
        "iban",
        "vat_number",
        "license_activities",
        "issue_date",
        "official_email",
        "official_mobile",
        "operating_name",
    ):
        field_entry = normalized.get(field_name)
        if isinstance(field_entry, dict):
            value = field_entry.get("value")
            if isinstance(value, str):
                field_entry["value"] = value.strip() or None
            normalized[field_name] = field_entry
    for field_name in ("qr_codes", "verification_urls"):
        field_entry = normalized.get(field_name)
        if isinstance(field_entry, dict):
            value = field_entry.get("value")
            if value is None:
                field_entry["value"] = []
            normalized[field_name] = field_entry
    return normalized


def _extraction_failed(reasoning: str) -> dict[str, Any]:
    return {"document_type": "unknown", "anomalies": ["Could not parse extraction output."], "reasoning": reasoning, "skipped": True}


def _extraction_unavailable(reasoning: str) -> dict[str, Any]:
    return {"document_type": "unknown", "anomalies": [reasoning], "reasoning": reasoning, "skipped": True}


def merge_llm_extraction_into_results(results: dict[str, Any], llm_extraction: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(results, dict) or not isinstance(llm_extraction, dict):
        return results
    merged = dict(results)
    for field_name, field_result in project_llm_extraction_fields(llm_extraction).items():
        value = field_result.get("value") if isinstance(field_result, dict) else None
        if value in (None, "", [], {}):
            continue
        merged[field_name] = field_result
    operating_name = llm_extraction.get("operating_name")
    if "TradeName" not in merged and isinstance(operating_name, dict):
        operating_value = operating_name.get("value")
        if operating_value not in (None, "", [], {}):
            merged["TradeName"] = operating_name
    return merged


def project_llm_extraction_fields(llm_extraction: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(llm_extraction, dict):
        return {}
    document_type = _normalize_llm_document_type(llm_extraction.get("document_type"))
    source_fields = {
        "trade": {
            "LicenseNo": "trade_license_number",
            "ExpiryDate": "expiry_date",
            "IssueDate": "issue_date",
            "IssuingAuthority": "issuing_authority",
            "LicenceActivities": "license_activities",
            "CompanyName": "company_name",
            "TradeName": "company_name",
            "TradeNameEnglish": "company_name",
            "OperatingName": "operating_name",
            "BusinessName": "company_name",
            "OfficialEmail": "official_email",
            "OfficialMobile": "official_mobile",
        },
        "vat": {
            "TaxRegistrationNumber": "vat_number",
            "LegalNameEnglish": "company_name",
            "LegalNameArabic": "company_name",
            "IssuingAuthority": "issuing_authority",
        },
        "bank": {
            "BankName": "bank_name",
            "AccountName": "company_name",
            "AccountNumber": "account_number",
            "IBAN": "iban",
            "SwiftCode": "bank_name",
            "IssuingAuthority": "issuing_authority",
        },
    }.get(document_type, {})
    projected: dict[str, dict[str, Any]] = {}
    for field_name, llm_field_name in source_fields.items():
        field_result = llm_extraction.get(llm_field_name)
        if isinstance(field_result, dict):
            projected[field_name] = field_result
    return projected


def _normalize_llm_document_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"trade", "trade license", "tradelicense", "trade licence", "trade license document"}:
        return "trade"
    if normalized in {"vat", "vat document", "tax", "tax document"}:
        return "vat"
    if normalized in {"bank", "bank letter", "bank document", "bank proof", "bank certificate", "bank offer"}:
        return "bank"
    return normalized or "unknown"


def build_trade_license_extras(
    raw_result: Any,
    extracted_fields: dict[str, Any],
    file_bytes: bytes | None = None,
    context_hint: Optional[str] = None,
) -> dict[str, Any]:
    extras = {
        "qr_payloads": build_qr_payloads_result(raw_result, file_bytes),
        "qr_codes": build_qr_codes_result(raw_result, file_bytes),
        "verification_urls": build_verification_urls_result(raw_result, file_bytes),
    }
    combined = review_and_extract_with_azure_openai(raw_result, extracted_fields, context_hint=context_hint)
    extras["gpt_review"] = combined.get("gpt_review", _review_failed("Missing gpt_review output"))
    extras["llm_extraction"] = combined.get("llm_extraction", _extraction_failed("Missing llm_extraction output"))
    return extras


def review_and_extract_with_azure_openai(
    raw_result: Any,
    extracted_fields: dict[str, Any],
    today: Optional[date] = None,
    deployment_name: Optional[str] = None,
    context_hint: Optional[str] = None,
) -> dict[str, Any]:
    if AzureOpenAI is None:
        return {
            "gpt_review": _review_unavailable("openai package is not installed"),
            "llm_extraction": _extraction_unavailable("openai package is not installed"),
        }
    try:
        client, deployment = _build_openai_client_and_deployment(deployment_name)
        if client is None or deployment is None:
            unavailable = _review_unavailable("Missing review configuration")
            unavailable_extraction = _extraction_unavailable("Missing extraction configuration")
            return {"gpt_review": unavailable, "llm_extraction": unavailable_extraction}
        resolved_today = today or date.today()
        raw_text = _combined_text(client, raw_result, extracted_fields, deployment, resolved_today, context_hint=context_hint)
        return _parse_combined_output(raw_text, resolved_today)
    except Exception as exc:
        logging.error("Azure OpenAI combined review/extraction failed: %s", exc)
        return {
            "gpt_review": _review_failed(str(exc)),
            "llm_extraction": _extraction_failed(str(exc)),
        }

def _combined_text(
    client: AzureOpenAI,
    raw_result: Any,
    extracted_fields: dict[str, Any],
    deployment: str,
    today: date,
    context_hint: Optional[str] = None,
) -> str:
    response = client.chat.completions.create(
        model=deployment,
        messages=_combined_messages(raw_result, extracted_fields, today, context_hint=context_hint),
        temperature=0,
        max_tokens=_review_max_tokens(),
    )
    return (response.choices[0].message.content or "").strip()


def _review_max_tokens() -> int:
    return max(document_review_openai_min_tokens(), document_review_openai_max_tokens())


def _parse_combined_output(raw_text: str, today: date) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "gpt_review": _review_failed(raw_text),
            "llm_extraction": _extraction_failed(raw_text),
        }
    gpt_review = parsed.get("gpt_review")
    llm_extraction = parsed.get("llm_extraction")
    return {
        "gpt_review": gpt_review if isinstance(gpt_review, dict) else _review_failed(raw_text),
        "llm_extraction": _normalize_extraction(llm_extraction if isinstance(llm_extraction, dict) else _extraction_failed(raw_text), today),
    }
