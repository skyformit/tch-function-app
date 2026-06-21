from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from app.infrastructure.document_logo_extraction import extract_logo_presence_from_pdf
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
) -> dict[str, Any]:
    result = evaluate_document_acceptance(document_type, payload, today=today, file_bytes=file_bytes)
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


_TRADE_LICENSE_NUMBER_FIELDS = ("LicenseNo", "LicenseNumber", "LicenceNo", "LicenceNumber")
_TRADE_LICENSE_EXPIRY_FIELDS = ("ExpiryDate",)
_TRADE_LICENSE_ACTIVITY_FIELDS = ("LicenceActivities", "LicenseActivities", "License Activities", "Licence Activities")

_VAT_NUMBER_FIELDS = ("TaxRegistrationNumber", "TRN", "VATNumber", "VATRegistrationNumber")
_VAT_NAME_FIELDS = ("LegalNameEnglish", "CompanyName", "LegalName")

_BANK_NAME_FIELDS = ("AccountName", "CompanyName", "LegalNameEnglish", "BeneficiaryName", "AccountHolderName", "AccountHolder")


def evaluate_document_acceptance(
    document_type: str,
    payload: dict[str, Any],
    today: Optional[date] = None,
    file_bytes: bytes | None = None,
) -> DocumentAcceptanceResult:
    normalized_type = _normalize_document_type(document_type)
    today = today or date.today()
    results = _results_section(payload)

    if normalized_type == "trade":
        return _evaluate_trade_license(payload, results, today, file_bytes=file_bytes)
    if normalized_type == "vat":
        return _evaluate_vat(results)
    if normalized_type == "bank":
        return _evaluate_bank(results)
    return DocumentAcceptanceResult(document_type=normalized_type, status="rejected", score=0, missing_fields=[], reasons=[f"Unsupported document type: {document_type}"])


def _evaluate_trade_license(
    payload: dict[str, Any],
    results: dict[str, Any],
    today: date,
    file_bytes: bytes | None = None,
) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []
    reasons: list[str] = []

    license_number = _first_value(results, _TRADE_LICENSE_NUMBER_FIELDS)
    expiry_date_text = _first_value(results, _TRADE_LICENSE_EXPIRY_FIELDS)
    licensed_activities = _first_value(results, _TRADE_LICENSE_ACTIVITY_FIELDS)

    if not license_number:
        missing_fields.append("license_number")
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

    if missing_fields:
        return _result("trade", "rejected", missing_fields, reasons, expiry_date=expiry_date, is_expired=bool(expiry_date is not None and expiry_date < today))

    score = 60
    if _signal_present(payload, "qr_codes"):
        score += 20
        reasons.append("QR code present.")
    else:
        reasons.append("QR code not found.")
    if _signal_present(payload, "verification_urls"):
        score += 20
        reasons.append("Verification URL present.")
    else:
        reasons.append("Verification URL not found.")

    if file_bytes is not None:
        if extract_logo_presence_from_pdf(file_bytes):
            score += 10
            reasons.append("Logo present.")
        else:
            reasons.append("Logo not found.")

    gpt_review = _gpt_review(payload)
    if gpt_review is not None:
        if gpt_review.get("skipped"):
            reasons.append(f"Expert review unavailable: {gpt_review.get('reasoning') or 'not configured'}.")
        else:
            gpt_score = _gpt_review_weight(gpt_review)
            score += gpt_score
            score = min(score, 100)
            reasons.append(f"Expert review contribution: +{gpt_score}.")

    score = min(score, 100)
    return _result("trade", _status_from_score(score), [], reasons, score_override=score, expiry_date=expiry_date, is_expired=bool(expiry_date is not None and expiry_date < today))


def _evaluate_vat(results: dict[str, Any]) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []
    reasons: list[str] = []

    tax_number = _first_value(results, _VAT_NUMBER_FIELDS)
    company_name = _first_value(results, _VAT_NAME_FIELDS)

    if not tax_number:
        missing_fields.append("vat_number")
    if not company_name:
        missing_fields.append("company_name")

    if missing_fields:
        return _result("vat", "rejected", missing_fields, reasons)

    return _result("vat", _status_from_score(100), [], reasons)


def _evaluate_bank(results: dict[str, Any]) -> DocumentAcceptanceResult:
    missing_fields: list[str] = []
    reasons: list[str] = []

    company_name = _first_value(results, _BANK_NAME_FIELDS)

    if not company_name:
        missing_fields.append("company_name")

    if missing_fields:
        return _result("bank", "rejected", missing_fields, reasons)

    return _result("bank", _status_from_score(100), [], reasons)


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


def _signal_present(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, dict):
        nested = value.get("value")
        return nested not in (None, "", [], {})
    return value not in (None, "", [], {})


def _gpt_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("gpt_review") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else None


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
    return round(15 * score)


def _status_from_score(score: int) -> str:
    if score >= 91:
        return "approved"
    if score >= 81:
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
    return normalized or "unknown"
