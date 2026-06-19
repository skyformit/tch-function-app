from app.use_cases.document_analysis_fallbacks import (
    _apply_bank_account_name_fallback,
    _apply_vat_analysis_fallback,
    _apply_vat_pdf_fallback,
    _collect_text_fragments,
    _extract_tax_registration_number_from_analysis_payload,
)
from app.use_cases.document_analysis_filters import _filter_results, _is_allowed_by_confidence, _is_allowed_by_validator
from app.use_cases.document_analysis_responses import build_document_analysis_response, build_trade_license_response
from app.use_cases.document_analysis_routes import run_document_analysis_route, run_trade_license_route
from app.use_cases.document_analysis_runtime import (
    AnalysisOutcome,
    _allow_analyze_without_upload,
    _collect_raw_field_keys,
    _debug_raw_keys_enabled,
    _provider,
    _upload_file,
    analyze_trade_license_document,
    build_trade_license_results,
    score_results,
)
from app.domain.document_analysis.profiles import DocumentAnalysisProfile
from app.infrastructure.document_text_extraction import extract_bank_account_name_from_pdf, extract_tax_registration_number_from_pdf
