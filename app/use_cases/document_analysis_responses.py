import logging
from typing import Any

from app.domain.document_analysis.extraction import extract_fields_with_confidence
from app.domain.document_analysis.profiles import DocumentAnalysisProfile, TRADE_LICENSE_PROFILE
from app.use_cases.document_analysis_filters import _filter_results
from app.use_cases.document_analysis_runtime import AnalysisOutcome, _collect_raw_field_keys, _debug_raw_keys_enabled, build_trade_license_results, score_results


def _response_payload(results: dict[str, dict[str, Any]], failure_message: str) -> dict[str, Any]:
    score = score_results(results)
    if any(value.get("value") not in (None, "", [], {}) for value in results.values()):
        return {"status": "success", "score": score, "results": results}
    return {"status": "fail", "score": score, "results": results, "error": {"code": "no_fields_found", "message": failure_message}}


def build_trade_license_response(outcome: AnalysisOutcome, target_fields: list[str]) -> dict[str, Any]:
    results = build_trade_license_results(outcome, target_fields)
    results = _filter_results(results, TRADE_LICENSE_PROFILE.minimum_confidence, TRADE_LICENSE_PROFILE.validators)
    return _response_payload(results, "No target trade license fields were extracted")


def build_document_analysis_response(outcome: AnalysisOutcome, profile: DocumentAnalysisProfile) -> dict[str, Any]:
    if profile.route_name == "ValidateVAT" and _debug_raw_keys_enabled():
        _log_raw_keys(outcome.raw_result)
    results = extract_fields_with_confidence(outcome.raw_result, profile.response_fields, field_aliases=profile.query_field_aliases)
    results = _filter_results(results, profile.minimum_confidence, profile.validators)
    return _response_payload(results, profile.failure_message)


def _log_raw_keys(raw_result: Any) -> None:
    raw_keys = _collect_raw_field_keys(raw_result)
    logging.info("VAT raw analyzer keys: top_level_keys=%s field_keys=%s", raw_keys["top_level_keys"], raw_keys["field_keys"])
