import asyncio
from typing import Optional, Tuple

import azure.functions as func
from azurefunctions.extensions.http.fastapi import Request

from app.domain.document_analysis.profiles import DocumentAnalysisProfile
from app.domain.document_analysis.profiles import TRADE_LICENSE_PROFILE
from app.infrastructure.document_logo_extraction import extract_logo_presence_from_pdf
from app.use_cases.company_name_matching import compare_company_names, normalize_company_name as _canonical_company_name
from app.use_cases.document_analysis_extras import build_qr_codes_result, build_qr_payloads_result, build_verification_urls_result
from app.infrastructure.storage.blob_storage import clean_name as _clean_name
from app.infrastructure.external.document_intelligence_client import analyze_document as analyze_with_document_intelligence
from app.use_cases.document_analysis_fallbacks import _apply_bank_account_name_fallback, _apply_vat_analysis_fallback
from app.use_cases.document_analysis_extras import build_trade_license_extras, extract_document_fields_with_azure_openai, merge_llm_extraction_into_results, review_with_azure_openai
from app.use_cases.document_analysis_extras import project_llm_extraction_fields
from app.use_cases.document_analysis_filters import _filter_results
from app.use_cases.document_analysis_runtime import DEFAULT_TARGET_FIELD_ALIASES
from app.domain.document_analysis.extraction import extract_fields_with_confidence
from app.use_cases.document_acceptance import build_document_acceptance_response
from app.use_cases.document_analysis_responses import build_document_analysis_response, build_trade_license_response
from app.use_cases.document_analysis_runtime import analyze_trade_license_document, score_results
from app.use_cases.general_bot_memory import get_conversation_entities, remember_trusted_trade_document
from core.foundry import _json_response


def _bad_request(message: str) -> func.HttpResponse:
    return _json_response({"ok": False, "error": {"code": "bad_request", "message": message}}, status_code=400)


def _raw_result_content_only(raw_result: object) -> str:
    if isinstance(raw_result, dict):
        value = raw_result.get("content")
        if isinstance(value, str):
            return value
        if value is not None:
            return str(value)
    return ""


async def _read_upload(req: Request) -> tuple[Optional[object], bytes, str, dict[str, str]]:
    form = await req.form()
    uploaded_file = form.get("file") or form.get("upload")
    if uploaded_file is None:
        return None, b"", "", {}
    extra_fields = {}
    for key in ("conversation_id", "company_name", "trade_license_number", "document_context", "context_hint"):
        value = form.get(key)
        if isinstance(value, str) and value.strip():
            extra_fields[key] = value.strip()
    return uploaded_file, await uploaded_file.read(), getattr(uploaded_file, "content_type", None), extra_fields


def _route_payload(
    profile: Optional[DocumentAnalysisProfile],
    is_trade: bool,
    outcome,
    file_bytes: bytes,
    content_type: Optional[str],
    target_fields: list[str],
    conversation_id: Optional[str] = None,
    requested_company_name: Optional[str] = None,
    context_hint: Optional[str] = None,
) -> dict:
    canonical_target_fields = _canonical_target_fields(profile, is_trade, target_fields)
    response_payload = build_trade_license_response(outcome, target_fields) if is_trade else build_document_analysis_response(outcome, profile)
    response_payload["raw_results"] = _raw_result_content_only(outcome.raw_result)
    if is_trade:
        extras = build_trade_license_extras(outcome.raw_result, response_payload.get("results", {}), file_bytes, context_hint=context_hint)
        response_payload.update(extras)
        _merge_document_signals(response_payload, outcome.raw_result, file_bytes)
        response_payload["results"] = merge_llm_extraction_into_results(response_payload.get("results", {}), response_payload["llm_extraction"])
        response_payload["results"] = _filter_results(response_payload["results"], TRADE_LICENSE_PROFILE.minimum_confidence, TRADE_LICENSE_PROFILE.validators)
        response_payload = _apply_missing_ocr_fallback(response_payload, file_bytes, content_type, canonical_target_fields, TRADE_LICENSE_PROFILE, DEFAULT_TARGET_FIELD_ALIASES)
        response_payload["results"] = _filter_results(response_payload["results"], TRADE_LICENSE_PROFILE.minimum_confidence, TRADE_LICENSE_PROFILE.validators)
        response_payload = _attach_company_match_details(
            response_payload,
            ["TradeName", "CompanyName", "TradeNameEnglish", "OperatingName", "BusinessName"],
            "company_match",
        )
        response_payload = _promote_llm_first_payload(response_payload)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}))
        response_payload["document_acceptance"] = build_document_acceptance_response(
            "trade",
            response_payload,
            file_bytes=file_bytes,
            requested_company_name=requested_company_name,
        )
        _remember_approved_trade_document(conversation_id, response_payload)
        return response_payload
    response_payload["llm_extraction"] = extract_document_fields_with_azure_openai(outcome.raw_result, context_hint=context_hint)
    response_payload["results"] = merge_llm_extraction_into_results(response_payload.get("results", {}), response_payload["llm_extraction"])
    query_field_aliases = getattr(profile, "query_field_aliases", {}) if profile is not None else {}
    minimum_confidence = getattr(profile, "minimum_confidence", {}) if profile is not None else {}
    validators = getattr(profile, "validators", {}) if profile is not None else {}
    if profile and profile.route_name == "ValidateVAT":
        response_payload = _apply_vat_analysis_fallback(response_payload, file_bytes, content_type)
        response_payload["results"] = _filter_results(response_payload["results"], minimum_confidence, validators)
        response_payload = _apply_missing_ocr_fallback(response_payload, file_bytes, content_type, canonical_target_fields, profile, query_field_aliases)
        response_payload["results"] = _filter_results(response_payload["results"], minimum_confidence, validators)
        _merge_document_signals(response_payload, outcome.raw_result, file_bytes)
        response_payload = _attach_company_match_details(
            response_payload,
            ["LegalNameEnglish", "LegalNameArabic", "CompanyName", "BusinessName"],
            "company_match",
        )
        response_payload = _promote_llm_first_payload(response_payload)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}), context_hint=context_hint)
        response_payload["document_acceptance"] = build_document_acceptance_response(
            "vat",
            response_payload,
            file_bytes=file_bytes,
            requested_company_name=requested_company_name,
        )
        return response_payload
    if profile and profile.route_name == "ValidateBankDocument":
        response_payload = _apply_bank_account_name_fallback(response_payload, file_bytes)
        response_payload["results"] = _filter_results(response_payload["results"], minimum_confidence, validators)
        response_payload = _apply_missing_ocr_fallback(response_payload, file_bytes, content_type, canonical_target_fields, profile, query_field_aliases)
        response_payload["results"] = _filter_results(response_payload["results"], minimum_confidence, validators)
        _merge_document_signals(response_payload, outcome.raw_result, file_bytes)
        response_payload = _attach_company_match_details(
            response_payload,
            ["AccountName", "CompanyName", "LegalNameEnglish", "BankName", "BeneficiaryName", "AccountHolderName", "AccountHolder"],
            "company_match",
        )
        response_payload = _promote_llm_first_payload(response_payload)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}), context_hint=context_hint)
        response_payload["document_acceptance"] = build_document_acceptance_response(
            "bank",
            response_payload,
            file_bytes=file_bytes,
            requested_company_name=requested_company_name,
        )
        return response_payload
    if profile and profile.route_name == "ValidateAffectionPlan":
        _merge_document_signals(response_payload, outcome.raw_result, file_bytes)
        response_payload = _promote_llm_first_payload(response_payload)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}), context_hint=context_hint)
        response_payload["document_acceptance"] = build_document_acceptance_response(
            "affection_plan",
            response_payload,
            file_bytes=file_bytes,
            requested_company_name=requested_company_name,
        )
        return response_payload
    response_payload = _promote_llm_first_payload(response_payload)
    response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}), context_hint=context_hint)
    return response_payload


def _promote_llm_first_payload(response_payload: dict) -> dict:
    results = response_payload.get("results")
    if not isinstance(results, dict) or not any(value.get("value") not in (None, "", [], {}) for value in results.values() if isinstance(value, dict)):
        return response_payload
    response_payload["status"] = "success"
    response_payload.pop("error", None)
    response_payload["score"] = score_results(results)
    return response_payload


def _canonical_target_fields(profile: Optional[DocumentAnalysisProfile], is_trade: bool, target_fields: list[str]) -> list[str]:
    if is_trade:
        return list(TRADE_LICENSE_PROFILE.response_fields)
    if profile is not None and getattr(profile, "response_fields", None):
        return list(profile.response_fields)
    return list(target_fields)


def _attach_document_signals(raw_result: object, file_bytes: bytes) -> dict:
    qr_payloads = build_qr_payloads_result(raw_result, file_bytes)
    qr_codes = build_qr_codes_result(raw_result, file_bytes)
    verification_urls = build_verification_urls_result(raw_result, file_bytes)
    logo_present = extract_logo_presence_from_pdf(file_bytes)
    return {
        "qr_payloads": qr_payloads,
        "qr_codes": qr_codes,
        "verification_urls": verification_urls,
        "logo": {"value": logo_present, "confidence": 1.0 if logo_present else 0.0},
    }


def _merge_document_signals(response_payload: dict, raw_result: object, file_bytes: bytes) -> None:
    for key, value in _attach_document_signals(raw_result, file_bytes).items():
        if key not in response_payload:
            response_payload[key] = value
            continue
        existing = response_payload.get(key)
        if isinstance(existing, dict):
            existing_value = existing.get("value")
            if existing_value not in (None, "", [], {}):
                continue
        response_payload[key] = value


def _attach_company_match_details(response_payload: dict, source_fields: list[str], match_key: str) -> dict:
    results = response_payload.get("results")
    llm_extraction = response_payload.get("llm_extraction")
    if not isinstance(results, dict) or not isinstance(llm_extraction, dict):
        return response_payload
    requested_company_name = _llm_company_name(llm_extraction)
    matched_company_name = _first_company_name(results, source_fields)
    if not requested_company_name or not matched_company_name:
        return response_payload
    comparison = compare_company_names(requested_company_name, matched_company_name)
    response_payload[match_key] = {
        "requested_company_name": comparison.string1,
        "requested_company_name_normalized": comparison.normalized1 or _canonical_company_name(comparison.string1),
        "matched_company_name": comparison.string2,
        "matched_company_name_normalized": comparison.normalized2 or _canonical_company_name(comparison.string2),
        "exact_match": comparison.exact_match,
        "similarity_percent": comparison.similarity_percent,
        "match_status": _match_status(comparison.similarity_percent, comparison.exact_match),
    }
    return response_payload


def _llm_company_name(llm_extraction: dict) -> str:
    value = llm_extraction.get("company_name")
    if isinstance(value, dict):
        candidate = value.get("value")
        if isinstance(candidate, str):
            return candidate.strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _first_company_name(results: dict, source_fields: list[str]) -> str:
    for field_name in source_fields:
        field_result = results.get(field_name)
        if not isinstance(field_result, dict):
            continue
        candidate = field_result.get("value")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _match_status(similarity_percent: float, exact_match: bool) -> str:
    if exact_match:
        return "exact"
    if similarity_percent >= 80:
        return "close"
    return "mismatch"


def _apply_missing_ocr_fallback(
    response_payload: dict,
    file_bytes: bytes,
    content_type: Optional[str],
    target_fields: list[str],
    profile: Optional[DocumentAnalysisProfile],
    field_aliases: dict[str, list[str]],
) -> dict:
    results = response_payload.get("results")
    llm_extraction = response_payload.get("llm_extraction")
    if not isinstance(results, dict) or not file_bytes:
        return response_payload
    missing_fields = _missing_fields_after_llm(target_fields, results, llm_extraction)
    if not missing_fields:
        return response_payload
    try:
        raw_result, _, _ = analyze_with_document_intelligence(file_bytes, content_type or "application/pdf", query_fields=missing_fields)
    except Exception:
        return response_payload
    fallback_results = extract_fields_with_confidence(raw_result, missing_fields, field_aliases=field_aliases)
    if profile is not None:
        normalized_results = {}
        for field_name, field_result in fallback_results.items():
            if isinstance(field_result, dict):
                normalized_result = dict(field_result)
                normalized_result["value"] = profile.normalize_field_value(field_name, normalized_result.get("value"))
                normalized_results[field_name] = normalized_result
        fallback_results = normalized_results
    for field_name, field_result in fallback_results.items():
        if isinstance(field_result, dict) and field_result.get("value") not in (None, "", [], {}):
            results.setdefault(field_name, field_result)
    response_payload["results"] = results
    return response_payload


def _missing_fields_after_llm(target_fields: list[str], results: dict[str, dict], llm_extraction: object) -> list[str]:
    projected_fields = project_llm_extraction_fields(llm_extraction if isinstance(llm_extraction, dict) else None)
    missing_fields: list[str] = []
    for field_name in target_fields:
        projected_result = projected_fields.get(field_name)
        if isinstance(projected_result, dict) and projected_result.get("value") not in (None, "", [], {}):
            continue
        if _field_missing(results, field_name):
            missing_fields.append(field_name)
    return missing_fields


def _field_missing(results: dict[str, dict], field_name: str) -> bool:
    field_result = results.get(field_name)
    if isinstance(field_result, dict):
        return field_result.get("value") in (None, "", [], {})
    return True


async def run_trade_license_route(req: Request, target_fields: list[str]) -> func.HttpResponse:
    return await _run_analysis_route(req, target_fields, None, True)


async def run_document_analysis_route(req: Request, profile: DocumentAnalysisProfile) -> func.HttpResponse:
    return await _run_analysis_route(req, profile.response_fields, profile, False)


async def _run_analysis_route(req: Request, target_fields: list[str], profile: Optional[DocumentAnalysisProfile], is_trade: bool) -> func.HttpResponse:
    if "multipart/form-data" not in (req.headers.get("content-type") or "").lower():
        return _bad_request("Provide multipart form-data with a 'file' field")
    uploaded_file, file_bytes, resolved_content_type, form_fields = await _read_upload(req)
    if uploaded_file is None:
        return _bad_request("Provide multipart form-data with a 'file' field")
    if not file_bytes:
        return _bad_request("Uploaded file is empty")
    file_name = _clean_name(getattr(uploaded_file, "filename", None), "upload.bin")
    context_hint = _build_document_context_hint(form_fields)
    outcome = await asyncio.to_thread(analyze_trade_license_document, file_name, file_bytes, resolved_content_type, target_fields, [])
    payload = _route_payload(
        profile,
        is_trade,
        outcome,
        file_bytes,
        resolved_content_type,
        target_fields,
        conversation_id=form_fields.get("conversation_id"),
        requested_company_name=_resolve_requested_company_name(form_fields),
        context_hint=context_hint or None,
    )
    return _json_response(payload, status_code=200)


def _build_document_context_hint(form_fields: dict[str, str]) -> str:
    parts: list[str] = []
    for label, key in (
        ("conversation_id", "conversation_id"),
        ("company_name", "company_name"),
        ("trade_license_number", "trade_license_number"),
        ("document_context", "document_context"),
        ("context_hint", "context_hint"),
    ):
        value = form_fields.get(key, "")
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts).strip()


def _resolve_requested_company_name(form_fields: dict[str, str]) -> str:
    requested_company_name = (form_fields.get("company_name") or "").strip()
    if requested_company_name:
        return requested_company_name
    conversation_id = (form_fields.get("conversation_id") or "").strip()
    if not conversation_id:
        return ""
    remembered_entities = get_conversation_entities(conversation_id)
    return (remembered_entities.get("company_name") or "").strip()


def _remember_approved_trade_document(conversation_id: Optional[str], response_payload: dict) -> None:
    if not conversation_id:
        return
    acceptance = response_payload.get("document_acceptance") if isinstance(response_payload.get("document_acceptance"), dict) else {}
    if acceptance.get("status") != "approved":
        return
    trade_document = {
        "document_type": "trade",
        "status": response_payload.get("status", "success"),
        "score": response_payload.get("score"),
        "company_name": _best_trade_company_name(response_payload),
        "trade_license_number": _best_trade_license_number(response_payload),
        "expiry_date": acceptance.get("expiry_date"),
        "is_expired": acceptance.get("is_expired"),
        "licensed_activities": _best_trade_activities(response_payload),
        "document_acceptance": acceptance,
        "results": response_payload.get("results", {}),
        "company_match": response_payload.get("company_match", {}),
        "gpt_review": response_payload.get("gpt_review", {}),
        "qr_codes": response_payload.get("qr_codes", {}),
        "verification_urls": response_payload.get("verification_urls", {}),
        "logo": response_payload.get("logo", {}),
    }
    remember_trusted_trade_document(conversation_id, trade_document)


def _best_trade_company_name(response_payload: dict) -> str:
    results = response_payload.get("results") if isinstance(response_payload.get("results"), dict) else {}
    for field_name in ("TradeName", "CompanyName", "TradeNameEnglish", "OperatingName", "BusinessName"):
        value = _field_value(results, field_name)
        if value:
            return value
    company_match = response_payload.get("company_match") if isinstance(response_payload.get("company_match"), dict) else {}
    for key in ("matched_company_name", "requested_company_name"):
        value = _clean_text(company_match.get(key))
        if value:
            return value
    return ""


def _best_trade_license_number(response_payload: dict) -> str:
    results = response_payload.get("results") if isinstance(response_payload.get("results"), dict) else {}
    for field_name in ("LicenseNo", "LicenceNumber", "LicenseNumber", "LicenceNo", "UnifiedLicenceNo", "UnifiedRegistrationNo"):
        value = _field_value(results, field_name)
        if value:
            return value
    return ""


def _best_trade_activities(response_payload: dict) -> str:
    results = response_payload.get("results") if isinstance(response_payload.get("results"), dict) else {}
    return _field_value(results, "LicenceActivities") or _field_value(results, "LicenseActivities") or ""


def _field_value(results: dict, field_name: str) -> str:
    field_result = results.get(field_name)
    if isinstance(field_result, dict):
        return _clean_text(field_result.get("value"))
    return ""


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()
