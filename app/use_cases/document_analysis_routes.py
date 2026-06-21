import asyncio
from typing import Optional, Tuple

import azure.functions as func
from azurefunctions.extensions.http.fastapi import Request

from app.domain.document_analysis.profiles import DocumentAnalysisProfile
from app.infrastructure.storage.blob_storage import clean_name as _clean_name
from app.use_cases.document_analysis_fallbacks import _apply_bank_account_name_fallback, _apply_vat_analysis_fallback
from app.use_cases.document_analysis_extras import build_trade_license_extras, extract_document_fields_with_azure_openai, merge_llm_extraction_into_results, review_with_azure_openai
from app.use_cases.document_acceptance import build_document_acceptance_response
from app.use_cases.document_analysis_responses import build_document_analysis_response, build_trade_license_response
from app.use_cases.document_analysis_runtime import analyze_trade_license_document
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


async def _read_upload(req: Request) -> tuple[Optional[object], bytes, str]:
    form = await req.form()
    uploaded_file = form.get("file") or form.get("upload")
    if uploaded_file is None:
        return None, b"", ""
    return uploaded_file, await uploaded_file.read(), getattr(uploaded_file, "content_type", None)


def _route_payload(profile: Optional[DocumentAnalysisProfile], is_trade: bool, outcome, file_bytes: bytes, content_type: Optional[str], target_fields: list[str]) -> dict:
    response_payload = build_trade_license_response(outcome, target_fields) if is_trade else build_document_analysis_response(outcome, profile)
    response_payload["raw_results"] = _raw_result_content_only(outcome.raw_result)
    if is_trade:
        extras = build_trade_license_extras(outcome.raw_result, response_payload.get("results", {}), file_bytes)
        response_payload.update(extras)
        response_payload["results"] = merge_llm_extraction_into_results(response_payload.get("results", {}), response_payload["llm_extraction"])
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}))
        response_payload["document_acceptance"] = build_document_acceptance_response("trade", response_payload, file_bytes=file_bytes)
        return response_payload
    response_payload["llm_extraction"] = extract_document_fields_with_azure_openai(outcome.raw_result)
    response_payload["results"] = merge_llm_extraction_into_results(response_payload.get("results", {}), response_payload["llm_extraction"])
    if profile and profile.route_name == "ValidateVAT":
        response_payload = _apply_vat_analysis_fallback(response_payload, file_bytes, content_type)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}))
        response_payload["document_acceptance"] = build_document_acceptance_response("vat", response_payload)
        return response_payload
    if profile and profile.route_name == "ValidateBankDocument":
        response_payload = _apply_bank_account_name_fallback(response_payload, file_bytes)
        response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}))
        response_payload["document_acceptance"] = build_document_acceptance_response("bank", response_payload)
        return response_payload
    response_payload["gpt_review"] = review_with_azure_openai(response_payload.get("results", {}))
    return response_payload


async def run_trade_license_route(req: Request, target_fields: list[str]) -> func.HttpResponse:
    return await _run_analysis_route(req, target_fields, None, True)


async def run_document_analysis_route(req: Request, profile: DocumentAnalysisProfile) -> func.HttpResponse:
    return await _run_analysis_route(req, profile.response_fields, profile, False)


async def _run_analysis_route(req: Request, target_fields: list[str], profile: Optional[DocumentAnalysisProfile], is_trade: bool) -> func.HttpResponse:
    if "multipart/form-data" not in (req.headers.get("content-type") or "").lower():
        return _bad_request("Provide multipart form-data with a 'file' field")
    uploaded_file, file_bytes, resolved_content_type = await _read_upload(req)
    if uploaded_file is None:
        return _bad_request("Provide multipart form-data with a 'file' field")
    if not file_bytes:
        return _bad_request("Uploaded file is empty")
    file_name = _clean_name(getattr(uploaded_file, "filename", None), "upload.bin")
    outcome = await asyncio.to_thread(analyze_trade_license_document, file_name, file_bytes, resolved_content_type, target_fields, getattr(profile, "query_fields", None))
    return _json_response(_route_payload(profile, is_trade, outcome, file_bytes, resolved_content_type, target_fields), status_code=200)
