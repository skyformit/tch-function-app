import logging
from typing import Any

from app.domain.document_analysis.extraction import extract_fields_with_confidence
from app.domain.document_analysis.profiles import DocumentAnalysisProfile, TRADE_LICENSE_PROFILE
from app.infrastructure.external.foundry.common import _with_response_metadata
from app.use_cases.document_analysis_filters import _filter_results
from app.use_cases.document_analysis_runtime import AnalysisOutcome, _collect_raw_field_keys, _debug_raw_keys_enabled, build_trade_license_results, score_results


def _response_payload(results: dict[str, dict[str, Any]], failure_message: str) -> dict[str, Any]:
    sanitized_results, source = _pop_response_source(results)
    score = score_results(sanitized_results)
    if any(value.get("value") not in (None, "", [], {}) for value in sanitized_results.values()):
        return _with_response_metadata({"status": "success", "score": score, "results": sanitized_results}, source)
    return _with_response_metadata({"status": "fail", "score": score, "results": sanitized_results, "error": {"code": "no_fields_found", "message": failure_message}}, source)


def _normalize_results(profile: DocumentAnalysisProfile, results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for field_name, field_result in results.items():
        if not isinstance(field_result, dict):
            continue
        normalized_result = dict(field_result)
        normalized_value = profile.normalize_field_value(field_name, normalized_result.get("value"))
        normalized_result["value"] = normalized_value
        normalized[field_name] = normalized_result
    return normalized


def _split_merged_unified_numbers(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged = results.get("LicenceNumber")
    if not isinstance(merged, dict):
        return results
    merged_value = merged.get("value")
    if not isinstance(merged_value, str):
        return results
    parts = [part for part in merged_value.split() if part.strip()]
    if len(parts) != 2:
        return results
    if any(not any(char.isdigit() for char in part) for part in parts):
        return results
    if "UnifiedRegistrationNo" in results or "UnifiedLicenceNo" in results:
        return results
    confidence = merged.get("confidence")
    updated = dict(results)
    updated["UnifiedRegistrationNo"] = {"value": parts[0], "confidence": confidence}
    updated["UnifiedLicenceNo"] = {"value": parts[1], "confidence": confidence}
    updated.pop("LicenceNumber", None)
    return updated


def _pop_response_source(results: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], str]:
    sanitized_results = dict(results)
    source_entry = sanitized_results.pop("_source", None)
    source = "document_intelligence"
    if isinstance(source_entry, dict):
        source = str(source_entry.get("value") or source).strip() or "document_intelligence"
    return sanitized_results, source


def build_trade_license_response(outcome: AnalysisOutcome, target_fields: list[str]) -> dict[str, Any]:
    results = build_trade_license_results(outcome, target_fields)
    results = _normalize_results(TRADE_LICENSE_PROFILE, results)
    results = _split_merged_unified_numbers(results)
    results = _filter_results(results, TRADE_LICENSE_PROFILE.minimum_confidence, TRADE_LICENSE_PROFILE.validators)
    results["_source"] = {"value": outcome.provider, "confidence": 1.0}
    return _response_payload(results, "No target trade license fields were extracted")


def build_document_analysis_response(outcome: AnalysisOutcome, profile: DocumentAnalysisProfile) -> dict[str, Any]:
    if profile.route_name == "ValidateVAT" and _debug_raw_keys_enabled():
        _log_raw_keys(outcome.raw_result)
    results = extract_fields_with_confidence(outcome.raw_result, profile.response_fields, field_aliases=profile.query_field_aliases)
    results = _normalize_results(profile, results)
    results = _filter_results(results, profile.minimum_confidence, profile.validators)
    results["_source"] = {"value": outcome.provider, "confidence": 1.0}
    return _response_payload(results, profile.failure_message)


def _log_raw_keys(raw_result: Any) -> None:
    raw_keys = _collect_raw_field_keys(raw_result)
    logging.info("VAT raw analyzer keys: top_level_keys=%s field_keys=%s", raw_keys["top_level_keys"], raw_keys["field_keys"])
