from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from app.core.document_policy import (
    approved_threshold,
    bank_base_score,
    bank_gpt_max_score,
    bank_issuing_authority_allowlist,
    bank_issuing_authority_score,
    bank_logo_score,
    review_threshold,
    trade_issuing_authority_allowlist,
    trade_vat_base_score,
    trade_vat_gpt_max_score,
    trade_vat_issuing_authority_score,
    trade_vat_logo_score,
    trade_vat_qr_score,
    trade_vat_verification_score,
    vat_issuing_authority_allowlist,
)
from app.infrastructure.document_logo_extraction import extract_logo_presence_from_pdf
from app.use_cases.company_name_matching import compare_company_names
from app.use_cases.trade_license_expiry import parse_trade_license_expiry_date


@dataclass(frozen=True)
class DocumentAcceptanceResult:
    document_type: str
    status: str
    score: int
    missing_fields: list[str]
    reasons: list[str]
    expiry_date: str | None = None
    is_expired: bool | None = None


def build_document_acceptance_response(
    document_type: str,
    payload: dict[str, Any],
    today: Optional[date] = None,
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> dict[str, Any]:
    result = evaluate_document_acceptance(document_type, payload, today=today, file_bytes=file_bytes, requested_company_name=requested_company_name)
    return {
        "document_type": result.document_type,
        "status": result.status,
        "score": result.score,
        "missing_fields": result.missing_fields,
        "reasons": result.reasons,
        "acceptable": result.status == "approved",
        "expiry_date": result.expiry_date,
        "is_expired": result.is_expired,
    }


_TRADE_LICENSE_NAME_FIELDS = ("TradeName", "CompanyName", "TradeNameEnglish", "OperatingName", "BusinessName")
_TRADE_LICENSE_EXPIRY_FIELDS = ("ExpiryDate",)
_TRADE_LICENSE_ACTIVITY_FIELDS = ("LicenceActivities", "LicenseActivities", "License Activities", "Licence Activities")
_ISSUING_AUTHORITY_FIELDS = ("IssuingAuthority",)

_VAT_NUMBER_FIELDS = ("TaxRegistrationNumber", "TRN", "VATNumber", "VATRegistrationNumber")
_VAT_NAME_FIELDS = ("LegalNameEnglish", "CompanyName", "LegalName")

_BANK_NAME_FIELDS = ("AccountName", "CompanyName", "LegalNameEnglish", "BeneficiaryName", "AccountHolderName", "AccountHolder")

_AFFECTION_PLAN_PARCEL_FIELDS = ("ParcelId", "ParcelNo", "PlotNumber", "PlotNo")
_AFFECTION_PLAN_AREA_FIELDS = ("TotalArea", "Area", "LandArea", "PlotArea")
_GPT_FRAUD_KEYWORDS = ("fake", "tamper", "tampered", "forged", "template", "inconsistent", "fabricated", "suspicious")


def evaluate_document_acceptance(
    document_type: str,
    payload: dict[str, Any],
    today: Optional[date] = None,
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> DocumentAcceptanceResult:
    normalized_type = _resolve_document_type(document_type, payload)
    today = today or date.today()
    results = _results_section(payload)

    if normalized_type == "trade":
        return _evaluate_trade_license(payload, results, today, file_bytes=file_bytes, requested_company_name=requested_company_name)
    if normalized_type == "vat":
        return _evaluate_vat(payload, results, file_bytes=file_bytes, requested_company_name=requested_company_name)
    if normalized_type == "bank":
        return _evaluate_bank(payload, results, file_bytes=file_bytes, requested_company_name=requested_company_name)
    if normalized_type == "affection_plan":
        return _evaluate_affection_plan(payload, results, file_bytes=file_bytes, requested_company_name=requested_company_name)
    return DocumentAcceptanceResult(document_type=normalized_type, status="rejected", score=0, missing_fields=[], reasons=[f"Unsupported document type: {document_type}"])


def _evaluate_trade_license(
    payload: dict[str, Any],
    results: dict[str, Any],
    today: date,
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []
    reasons: list[str] = []

    trade_name = _first_value(results, _TRADE_LICENSE_NAME_FIELDS)
    expiry_date_text = _first_value(results, _TRADE_LICENSE_EXPIRY_FIELDS)
    licensed_activities = _first_value(results, _TRADE_LICENSE_ACTIVITY_FIELDS)

    if not trade_name:
        missing_fields.append("trade_name")
    if not expiry_date_text:
        missing_fields.append("expiry_date")
    if not licensed_activities:
        missing_fields.append("licensed_activities")

    expiry_date = parse_trade_license_expiry_date(expiry_date_text)
    if expiry_date_text and expiry_date is None:
        reasons.append("Expiry date is present but could not be parsed.")
        missing_fields.append("expiry_date")
    elif expiry_date is not None and expiry_date < today:
        reasons.append("Trade license is expired.")
        missing_fields.append("expiry_date")

    requested_company_name = _normalize_text(requested_company_name)
    if requested_company_name and trade_name:
        comparison = compare_company_names(requested_company_name, trade_name)
        if not comparison.exact_match:
            missing_fields.append("company_name_mismatch")
            return _result(
                "trade",
                "rejected",
                missing_fields,
                [
                    f"Requested company name '{requested_company_name}' does not match uploaded trade license company name '{trade_name}'."
                ],
                score_override=0,
                expiry_date=expiry_date,
                is_expired=bool(expiry_date is not None and expiry_date < today),
            )

    if missing_fields:
        return _result("trade", "rejected", missing_fields, reasons, expiry_date=expiry_date, is_expired=bool(expiry_date is not None and expiry_date < today))

    fraud_risk_reason = _gpt_fraud_risk_reason(payload)
    if fraud_risk_reason is not None:
        return _result(
            "trade",
            "rejected",
            ["document_authenticity"],
            [fraud_risk_reason],
            score_override=0,
            expiry_date=expiry_date,
            is_expired=bool(expiry_date is not None and expiry_date < today),
        )

    authority_validation = _validate_issuing_authority("trade", results)
    authority_text, authority_bonus = authority_validation if authority_validation is not None else (None, None)
    return _score_with_signals(
        "trade",
        payload,
        file_bytes=file_bytes,
        authority_text=authority_text,
        authority_bonus=authority_bonus,
        expiry_date=expiry_date,
        is_expired=bool(expiry_date is not None and expiry_date < today),
    )


def _evaluate_vat(
    payload: dict[str, Any],
    results: dict[str, Any],
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []

    tax_number = _first_value(results, _VAT_NUMBER_FIELDS)
    company_name = _first_value(results, _VAT_NAME_FIELDS)

    if not tax_number:
        missing_fields.append("vat_number")
    if not company_name:
        missing_fields.append("company_name")

    if missing_fields:
        return _result("vat", "rejected", missing_fields, [])

    requested_company_name = _normalize_text(requested_company_name)
    if requested_company_name and company_name:
        comparison = compare_company_names(requested_company_name, company_name)
        if not comparison.exact_match:
            return _result(
                "vat",
                "rejected",
                ["company_name_mismatch"],
                [
                    f"Requested company name '{requested_company_name}' does not match uploaded VAT company name '{company_name}'."
                ],
                score_override=0,
            )

    fraud_risk_reason = _gpt_fraud_risk_reason(payload)
    if fraud_risk_reason is not None:
        return _result("vat", "rejected", ["document_authenticity"], [fraud_risk_reason], score_override=0)

    authority_validation = _validate_issuing_authority("vat", results)
    authority_text, authority_bonus = authority_validation if authority_validation is not None else (None, None)

    return _score_with_signals("vat", payload, file_bytes=file_bytes, authority_text=authority_text, authority_bonus=authority_bonus)


def _evaluate_bank(
    payload: dict[str, Any],
    results: dict[str, Any],
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []

    company_name = _first_value(results, _BANK_NAME_FIELDS)

    if not company_name:
        missing_fields.append("bank_name")

    if missing_fields:
        return _result("bank", "rejected", missing_fields, [])

    requested_company_name = _normalize_text(requested_company_name)
    if requested_company_name and company_name:
        comparison = compare_company_names(requested_company_name, company_name)
        if not comparison.exact_match:
            return _result(
                "bank",
                "rejected",
                ["company_name_mismatch"],
                [
                    f"Requested company name '{requested_company_name}' does not match uploaded bank document company name '{company_name}'."
                ],
                score_override=0,
            )

    fraud_risk_reason = _gpt_fraud_risk_reason(payload)
    if fraud_risk_reason is not None:
        return _result("bank", "rejected", ["document_authenticity"], [fraud_risk_reason], score_override=0)

    return _score_bank_with_logo_and_gpt(payload, file_bytes=file_bytes)


def _evaluate_affection_plan(
    payload: dict[str, Any],
    results: dict[str, Any],
    file_bytes: bytes | None = None,
    requested_company_name: str | None = None,
) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []

    parcel_id = _first_value(results, _AFFECTION_PLAN_PARCEL_FIELDS)
    total_area = _first_value(results, _AFFECTION_PLAN_AREA_FIELDS)

    if not parcel_id:
        missing_fields.append("parcel_id")
    if not total_area:
        missing_fields.append("total_area")

    if missing_fields:
        return _result("affection_plan", "rejected", missing_fields, [])

    fraud_risk_reason = _gpt_fraud_risk_reason(payload)
    if fraud_risk_reason is not None:
        return _result("affection_plan", "rejected", ["document_authenticity"], [fraud_risk_reason], score_override=0)

    return _score_with_signals("affection_plan", payload, file_bytes=file_bytes)


def _score_with_signals(
    document_type: str,
    payload: dict[str, Any],
    file_bytes: bytes | None = None,
    authority_text: str | None = None,
    authority_bonus: int | None = None,
    expiry_date: date | None = None,
    is_expired: bool | None = None,
) -> DocumentAcceptanceResult:
    score = trade_vat_base_score()
    reasons: list[str] = []

    if _signal_present(payload, "qr_codes"):
        score += trade_vat_qr_score()
        reasons.append("QR code present.")
    else:
        reasons.append("QR code not found.")

    if _signal_present(payload, "verification_urls"):
        score += trade_vat_verification_score()
        reasons.append("Verification URL present.")
    else:
        reasons.append("Verification URL not found.")

    if file_bytes is not None:
        if extract_logo_presence_from_pdf(file_bytes):
            score += trade_vat_logo_score()
            reasons.append("Logo present.")
        else:
            reasons.append("Logo not found.")

    if authority_bonus is None:
        authority_validation = _validate_issuing_authority(document_type, _results_section(payload))
        if authority_validation is not None:
            authority_text, authority_bonus = authority_validation
    if authority_bonus:
        score += authority_bonus
        reasons.append(f"Issuing authority present: {authority_text}. Expert boost: +{authority_bonus}.")

    gpt_review = _gpt_review(payload)
    if gpt_review is not None:
        if gpt_review.get("skipped"):
            reasons.append(f"Expert review unavailable: {gpt_review.get('reasoning') or 'not configured'}.")
        else:
            gpt_score = _gpt_review_weight(gpt_review)
            score += gpt_score
            reasons.append(f"Expert review contribution: +{gpt_score}.")

    return _result(document_type, _status_from_score(score), [], reasons, score_override=score, expiry_date=expiry_date, is_expired=is_expired)


def _score_bank_with_logo_and_gpt(
    payload: dict[str, Any],
    file_bytes: bytes | None = None,
) -> DocumentAcceptanceResult:
    score = bank_base_score()
    reasons: list[str] = []

    if file_bytes is not None:
        if extract_logo_presence_from_pdf(file_bytes):
            score += bank_logo_score()
            reasons.append("Logo present.")
        else:
            reasons.append("Logo not found.")

    gpt_review = _gpt_review(payload)
    if gpt_review is not None:
        if gpt_review.get("skipped"):
            reasons.append(f"Expert review unavailable: {gpt_review.get('reasoning') or 'not configured'}.")
        else:
            gpt_score = _bank_gpt_review_weight(gpt_review)
            score += gpt_score
            reasons.append(f"Expert review contribution: +{gpt_score}.")

    score = min(score, 100)
    return _result("bank", _status_from_score(score), [], reasons, score_override=score)


def _bank_gpt_review_weight(gpt_review: dict[str, Any]) -> int:
    plausibility = gpt_review.get("plausibility_score")
    try:
        score = float(plausibility)
    except (TypeError, ValueError):
        score = 0.0
    if score < 0:
        score = 0.0
    if score > 1:
        score = 1.0
    return round(bank_gpt_max_score() * score)


def _result(
    document_type: str,
    status: str,
    missing_fields: list[str],
    reasons: list[str],
    score_override: Optional[int] = None,
    expiry_date: date | None = None,
    is_expired: bool | None = None,
) -> DocumentAcceptanceResult:
    score = score_override if score_override is not None else (100 if status == "approved" else max(0, 100 - (len(missing_fields) * 30) - (10 if reasons else 0)))
    expiry_date_text = expiry_date.isoformat() if expiry_date else None
    return DocumentAcceptanceResult(document_type=document_type, status=status, score=score, missing_fields=missing_fields, reasons=reasons, expiry_date=expiry_date_text, is_expired=is_expired)


def _results_section(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), dict):
        return payload["results"]
    if isinstance(payload, dict):
        return payload
    return {}


def _first_value(results: dict[str, Any], field_names: Iterable[str]) -> Any:
    for field_name in field_names:
        field_result = results.get(field_name)
        if isinstance(field_result, dict):
            value = field_result.get("value")
            if value not in (None, "", [], {}):
                return value
        elif field_result not in (None, "", [], {}):
            return field_result
    return None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _signal_present(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, dict):
        nested = value.get("value")
        return nested not in (None, "", [], {})
    return value not in (None, "", [], {})


def _gpt_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("gpt_review") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else None


def _gpt_fraud_risk_reason(payload: dict[str, Any]) -> str | None:
    gpt_review = _gpt_review(payload)
    if gpt_review is None or gpt_review.get("skipped"):
        return None
    try:
        plausibility = float(gpt_review.get("plausibility_score"))
    except (TypeError, ValueError):
        plausibility = 0.0
    if plausibility >= 0.4:
        anomalies = gpt_review.get("anomalies")
        if not isinstance(anomalies, list):
            return None
        suspicious_anomaly = _first_suspicious_anomaly(anomalies)
        if suspicious_anomaly is None:
            return None
        return f"GPT review indicates fraud risk: {suspicious_anomaly}"
    anomalies = gpt_review.get("anomalies")
    suspicious_anomaly = _first_suspicious_anomaly(anomalies if isinstance(anomalies, list) else [])
    if suspicious_anomaly is not None:
        return f"GPT review indicates fraud risk: {suspicious_anomaly}"
    return "GPT review plausibility score is too low."


def _validate_issuing_authority(document_type: str, results: dict[str, Any]) -> tuple[str, int] | None:
    authority = _normalize_text(_first_value(results, _authority_fields_for_document(document_type)))
    if not authority:
        return None
    lowered = authority.lower()
    if document_type == "trade":
        if _matches_allowlist(lowered, trade_issuing_authority_allowlist()):
            return authority, trade_vat_issuing_authority_score()
        return None
    if document_type == "vat":
        if _matches_allowlist(lowered, vat_issuing_authority_allowlist()):
            return authority, trade_vat_issuing_authority_score()
        return None
    if document_type == "bank":
        if _matches_allowlist(lowered, bank_issuing_authority_allowlist()):
            return authority, bank_issuing_authority_score()
        return None
    return None


def _authority_fields_for_document(document_type: str) -> tuple[str, ...]:
    if document_type == "bank":
        return ("IssuingAuthority", "BankName")
    return _ISSUING_AUTHORITY_FIELDS


def _matches_allowlist(value: str, allowlist: Iterable[str]) -> bool:
    return any(token in value for token in allowlist)


def _first_suspicious_anomaly(anomalies: list[Any]) -> str | None:
    for anomaly in anomalies:
        if not isinstance(anomaly, str):
            continue
        lowered = anomaly.lower()
        if any(keyword in lowered for keyword in _GPT_FRAUD_KEYWORDS):
            return anomaly
    return None


def _gpt_review_weight(gpt_review: dict[str, Any]) -> int:
    plausibility = gpt_review.get("plausibility_score")
    try:
        score = float(plausibility)
    except (TypeError, ValueError):
        score = 0.0
    if score < 0:
        score = 0.0
    if score > 1:
        score = 1.0
    return round(trade_vat_gpt_max_score() * score)


def _status_from_score(score: int) -> str:
    if score >= approved_threshold():
        return "approved"
    if score >= review_threshold():
        return "review"
    return "rejected"


def _normalize_document_type(document_type: str) -> str:
    normalized = (document_type or "").strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"trade", "trade license", "tradelicense", "trade licence", "trade license document"}:
        return "trade"
    if normalized in {"vat", "vat document", "tax", "tax document"}:
        return "vat"
    if normalized in {"bank", "bank letter", "bank document", "bank proof"}:
        return "bank"
    if normalized in {"affection plan", "affectionplan", "plot", "plot document", "land document"}:
        return "affection_plan"
    return normalized or "unknown"


def _resolve_document_type(document_type: str, payload: dict[str, Any]) -> str:
    payload_document_type = None
    if isinstance(payload, dict):
        llm_extraction = payload.get("llm_extraction")
        if isinstance(llm_extraction, dict):
            payload_document_type = llm_extraction.get("document_type")

    resolved_route_type = _normalize_document_type(document_type)
    resolved_payload_type = _normalize_document_type(str(payload_document_type or ""))

    if resolved_payload_type in {"trade", "vat", "bank", "affection_plan"}:
        return resolved_payload_type
    return resolved_route_type
