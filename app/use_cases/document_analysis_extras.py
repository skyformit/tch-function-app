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
    return (
    "You are a highly accurate document extraction engine specialized in OCR outputs from Trade Licenses, VAT Certificates, Bank Letters, Bank Certificates, and other supplier onboarding documents.\n\n"

    "You will receive raw OCR or document analysis content extracted from PDFs, scanned images, or digital documents.\n\n"

    "Your task is to extract structured information from the document and return ONLY valid JSON.\n\n"

    "GENERAL PRINCIPLES\n"
    "- Extract information ONLY from the provided document text.\n"
    "- Never use external knowledge.\n"
    "- Never infer, fabricate, guess, complete, or hallucinate information.\n"
    "- Search the ENTIRE document before determining that a field is unavailable.\n"
    "- Perform semantic matching, not only exact label matching.\n"
    "- Support multilingual documents including English, Arabic, and mixed-language documents.\n"
    "- Preserve extracted values exactly as they appear in the document.\n"
    "- Normalize whitespace only.\n"
    "- Do not reformat dates, names, account numbers, VAT numbers, license numbers, IBANs, or other extracted values.\n"
    "- If multiple candidate values are found, build an internal candidate list and select the best match.\n"
    "- Prefer values closest to the associated field label.\n"
    "- Prefer complete values over partial values.\n"
    "- Prefer machine-readable values over fragmented OCR fragments.\n"
    "- If a value cannot be identified with reasonable confidence, return null.\n\n"

    "DOCUMENT CLASSIFICATION\n"
    "- Determine the document type using document content.\n"
    "- Allowed values: trade, vat, bank_certificate, bank_offer, bank, unknown.\n"
    "- Use bank_certificate for bank letters / certificates / statements.\n"
    "- Use bank_offer for bank offer letters or offer documents.\n"
    "- Use bank when the document is clearly a generic bank document and the subtype is not obvious.\n"
    "- If uncertain, use unknown.\n\n"

    "FIELD MATCHING STRATEGY\n"
    "- Do not rely only on exact field names.\n"
    "- Match semantic equivalents, OCR variations, abbreviations, multilingual labels, and synonyms.\n"
    "- Always attempt to find the closest matching field before returning null.\n"
    "- If no reliable match exists, return null.\n\n"

    "FIELD SYNONYMS\n\n"

    "trade_license_number:\n"
    "- License No\n"
    "- Licence No\n"
    "- Trade License No\n"
    "- Trade Licence No\n"
    "- Commercial License No\n"
    "- Industrial License No\n"
    "- Registration License No\n"
    "- Permit Number\n"
    "- License Number\n"
    "- Licence Number\n"
    "- Registration Number\n"
    "- Registration No\n"
    "- Commercial Registration Number\n"
    "- CR Number\n"
    "- رقم الرخصة\n"
    "- رقم التسجيل\n\n"

    "company_name:\n"
    "- Company Name\n"
    "- Legal Entity Name\n"
    "- Entity Name\n"
    "- Licensee\n"
    "- Establishment Name\n"
    "- Organization Name\n"
    "- Registered Name\n"
    "- Business Name\n"
    "- Corporate Name\n"
    "- صاحب الرخصة\n"
    "- اسم الشركة\n\n"
    "- Return the full legal company name only.\n"
    "- Do not return partial fragments, trailing suffix lines, or standalone legal suffixes.\n"
    "- If the company name is split across lines, combine the lines when they clearly belong together.\n"
    "- Prefer the longest complete name that still looks like a real company name.\n"
    "- Do not return values like \"INDUSTRIES L.L.C\", \"LLC\", \"CO.\", \"BRANCH\", \"ESTABLISHMENT\", \"SOLE PROPRIETORSHIP\", or \"TRADING\" when they are only trailing fragment lines.\n"
    "- If only a fragment is present, return null.\n\n"

    "operating_name:\n"
    "- Operating Name\n"
    "- Trade Name\n"
    "- Commercial Name\n"
    "- Trading Name\n"
    "- Brand Name\n"
    "- الاسم التجاري\n\n"
    "- Return the full operating/trade name only.\n"
    "- Do not return partial fragments or trailing legal suffix lines.\n"
    "- If the trade name is split across lines, combine the lines when they clearly belong together.\n"
    "- Prefer the longest complete name that still looks like a real company name.\n"
    "- Do not return trailing fragment lines such as \"SOLE PROPRIETORSHIP\" or \"TRADING\" when they are only suffix text.\n"
    "- If only a fragment is present, return null.\n\n"

    "expiry_date:\n"
    "- Expiry Date\n"
    "- Expiration Date\n"
    "- Valid Until\n"
    "- Valid Till\n"
    "- License Expiry\n"
    "- Date of Expiry\n"
    "- Renewal Date\n"
    "- تاريخ الانتهاء\n\n"

    "issue_date:\n"
    "- Issue Date\n"
    "- Date of Issue\n"
    "- Issued On\n"
    "- License Date\n"
    "- Registration Date\n"
    "- تاريخ الإصدار\n\n"

    "issuing_authority:\n"
    "- Issuing Authority\n"
    "- Authority\n"
    "- Issued By\n"
    "- License Issuing Authority\n"
    "- Registration Authority\n"
    "- Department\n"
    "- جهة الترخيص\n"
    "- جهة الإصدار\n"
    "- صادر عن\n\n"
    "- For trade licenses, prefer the actual licensing body over a generic government header.\n"
    "- Mainland examples include Department of Economy and Tourism, Department of Economic Development, DED, DET, ADDED, SEDD, and similar emirate licensing bodies.\n"
    "- Free zone examples include JAFZA, DAFZA, IFZA, RAKEZ/KEZAD/KIZAD, DMCC, DIFC, Dubai South, Meydan Free Zone, Dubai Silicon Oasis, Hamriyah Free Zone, Sharjah Airport International Free Zone, SAIF Zone, Fujairah Free Zone, Umm Al Quwain Free Trade Zone, and similar free-zone authorities.\n"
    "- For VAT documents, prefer Federal Tax Authority / FTA / الهيئة الاتحادية للضرائب.\n"
    "- If the document shows a generic header such as Government of Dubai and also shows a more specific licensing body in the license details section, choose the more specific licensing body.\n"
    "- If only a generic header is present and no specific licensing body can be identified, return that generic header only as a fallback.\n\n"

    "vat_number:\n"
    "- VAT Number\n"
    "- VAT Registration Number\n"
    "- TRN\n"
    "- Tax Registration Number\n"
    "- Tax Registration No\n"
    "- VAT Registration No\n"
    "- رقم التسجيل الضريبي\n\n"

    "bank_name:\n"
    "- Bank Name\n"
    "- Banker\n"
    "- Banking Institution\n"
    "- Financial Institution\n"
    "- Bank\n"
    "- اسم البنك\n\n"

    "account_number:\n"
    "- Account Number\n"
    "- Account No\n"
    "- A/C Number\n"
    "- Customer Account Number\n"
    "- Bank Account Number\n"
    "- رقم الحساب\n\n"

    "iban:\n"
    "- IBAN\n"
    "- International Bank Account Number\n"
    "- IBAN Number\n"
    "- رقم الآيبان\n\n"

    "official_email:\n"
    "- Email\n"
    "- Official Email\n"
    "- Contact Email\n"
    "- Corporate Email\n"
    "- E-mail\n"
    "- البريد الإلكتروني\n\n"

    "official_mobile:\n"
    "- Mobile\n"
    "- Phone\n"
    "- Telephone\n"
    "- Contact Number\n"
    "- Official Mobile\n"
    "- Mobile Number\n"
    "- رقم الهاتف\n"
    "- الجوال\n\n"

    "license_activities:\n"
    "- Activities\n"
    "- Business Activities\n"
    "- Licensed Activities\n"
    "- Commercial Activities\n"
    "- Industrial Activities\n"
    "- Activity\n"
    "- النشاط\n"
    "- الأنشطة\n\n"

    "MULTILINGUAL SUPPORT\n"
    "- Documents may contain English, Arabic, or mixed-language content.\n"
    "- Use labels from either language.\n"
    "- Extract the value regardless of the language used.\n\n"

    "CONFIDENCE SCORING\n"
    "- Confidence must reflect extraction certainty.\n"
    "- Use numeric values between 0.00 and 1.00.\n"
    "- 0.95–1.00: Explicit label and clear value association.\n"
    "- 0.80–0.94: Strong semantic match with minor OCR noise.\n"
    "- 0.60–0.79: Likely correct but multiple candidates exist.\n"
    "- Below 0.60: Return null instead of the value.\n"
    "- If value is null, confidence must also be null.\n\n"

    "DATE HANDLING\n"
    "- Extract dates exactly as shown.\n"
    "- Do not reformat dates.\n"
    "- Examples:\n"
    "  - 29/11/2000\n"
    "  - 2027-01-10\n"
    "  - 10 JAN 2027\n\n"

    "IS_EXPIRED\n"
    "- Calculate only if a valid expiry date is found.\n"
    "- If expiry date is before today's date, return true.\n"
    "- If expiry date is today or later, return false.\n"
    "- If expiry date is unavailable, return null.\n"
    "- Confidence should reflect certainty of the expiry date extraction.\n\n"

    "QR CODE EXTRACTION\n"
    "- Extract QR payload values if explicitly present in OCR text.\n"
    "- Extract embedded verification references.\n"
    "- Remove duplicates.\n"
    "- Return an empty array if none are found.\n\n"

    "VERIFICATION URL EXTRACTION\n"
    "- Extract all verification URLs.\n"
    "- Extract validation portals.\n"
    "- Extract authenticity verification links.\n"
    "- Remove duplicates.\n"
    "- Return an empty array if none are found.\n\n"

    "INTERNAL EXTRACTION PROCESS\n"
    "- First scan the entire document.\n"
    "- Build an internal candidate list for each field.\n"
    "- Evaluate label proximity.\n"
    "- Evaluate semantic similarity.\n"
    "- Evaluate OCR confidence.\n"
    "- Select the strongest candidate.\n"
    "- Only return values that meet the confidence threshold.\n"
    "- Never expose intermediate reasoning.\n\n"

    "OUTPUT REQUIREMENTS\n"
    "- Return ONLY valid JSON.\n"
    "- No markdown.\n"
    "- No explanations.\n"
    "- No notes.\n"
    "- No additional fields.\n"
    "- Follow the schema exactly.\n\n"

    "Use this exact output schema:\n"
    "{\n"
    '  "document_type": "trade|vat|bank_certificate|bank_offer|bank|unknown",\n'
    '  "trade_license_number": {"value": null, "confidence": null},\n'
    '  "expiry_date": {"value": null, "confidence": null},\n'
    '  "is_expired": {"value": null, "confidence": null},\n'
    '  "company_name": {"value": null, "confidence": null},\n'
    '  "issuing_authority": {"value": null, "confidence": null},\n'
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
    "}\n"
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
    return (
        "You are a document intelligence assistant.\n"
        "You must produce both a document review and a document extraction in a single JSON response.\n\n"
        "gpt_review: inspect the extracted fields for internal inconsistencies, implausible values, placeholder/test data, date logic errors, formatting that looks machine-altered, or anything that suggests the document is fake, templated, tampered with, or suspicious. Use only internal consistency and plausibility. If a standard issuing authority is present and plausible for the document type, treat it as supporting evidence. For trade documents, mainland licensing bodies such as Department of Economy and Tourism, Department of Economic Development, DED, DET, ADDED, SEDD, and common free-zone authorities such as JAFZA, DAFZA, IFZA, RAKEZ/KEZAD/KIZAD, DMCC, DIFC, Dubai South, Meydan Free Zone, Dubai Silicon Oasis, Hamriyah Free Zone, Sharjah Airport International Free Zone, SAIF Zone, Fujairah Free Zone, and Umm Al Quwain Free Trade Zone should be treated as valid authority evidence. For VAT, Federal Tax Authority / FTA / الهيئة الاتحادية للضرائب is the expected authority. For bank documents, the bank, branch, or financial institution name is the expected authority evidence. Do not treat one malformed email domain, truncated authority name, or other OCR artifact as fraud by itself. Only lower plausibility sharply when multiple signals agree that the document is fake, tampered with, template-like, or internally contradictory. If fraud risk is present, lower plausibility_score and say so directly in anomalies and reasoning.\n\n"
        "llm_extraction: extract the key document fields exactly as they appear in the raw OCR/document analysis JSON. Do not guess or invent. Trim whitespace only. For issuing_authority, prefer the specific licensing or tax authority field tied to the document's primary license/details block. For trade documents, choose the actual issuing licensing body over a generic government header whenever both appear; mainland examples include Department of Economy and Tourism, Department of Economic Development, DED, DET, ADDED, and SEDD, while free-zone examples include JAFZA, DAFZA, IFZA, RAKEZ/KEZAD/KIZAD, DMCC, DIFC, Dubai South, Meydan Free Zone, Dubai Silicon Oasis, Hamriyah Free Zone, Sharjah Airport International Free Zone, SAIF Zone, Fujairah Free Zone, and Umm Al Quwain Free Trade Zone. For VAT, prefer Federal Tax Authority / FTA / الهيئة الاتحادية للضرائب. For bank documents, prefer the bank or financial institution name. Do not use footer verification text, chamber footer text, or marketing text unless no better authority is present. If multiple authority-like strings appear, choose the one tied to the document's primary license/details block.\n\n"
        "Return ONLY valid JSON. No markdown. No explanation.\n"
        "Use this exact output schema:\n"
        "{\n"
        '  "gpt_review": {\n'
        '    "is_consistent": true,\n'
        '    "anomalies": [],\n'
        '    "plausibility_score": 0.0,\n'
        '    "reasoning": ""\n'
        "  },\n"
        '  "llm_extraction": {\n'
        '    "document_type": "trade|vat|bank_certificate|bank_offer|bank|unknown",\n'
        '    "trade_license_number": {"value": null, "confidence": null},\n'
        '    "expiry_date": {"value": null, "confidence": null},\n'
        '    "is_expired": {"value": null, "confidence": null},\n'
        '    "company_name": {"value": null, "confidence": null},\n'
        '    "issuing_authority": {"value": null, "confidence": null},\n'
        '    "bank_name": {"value": null, "confidence": null},\n'
        '    "account_number": {"value": null, "confidence": null},\n'
        '    "iban": {"value": null, "confidence": null},\n'
        '    "vat_number": {"value": null, "confidence": null},\n'
        '    "license_activities": {"value": null, "confidence": null},\n'
        '    "issue_date": {"value": null, "confidence": null},\n'
        '    "official_email": {"value": null, "confidence": null},\n'
        '    "official_mobile": {"value": null, "confidence": null},\n'
        '    "operating_name": {"value": null, "confidence": null},\n'
        '    "qr_codes": {"value": [], "confidence": null},\n'
        '    "verification_urls": {"value": [], "confidence": null}\n'
        "  }\n"
        "}"
    )


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
