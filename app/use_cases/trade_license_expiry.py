from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None

EXPIRY_PATTERN = re.compile(r"(?:Trade License Expiry Date|Expiry Date)\s*:\s*([^\r\n]+)", re.IGNORECASE)
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%Y %B %d",
    "%Y %b %d",
)


@dataclass(frozen=True)
class TradeLicenseExpiryDecision:
    expiry_date: date
    days_remaining: int
    status: str


def _today() -> date:
    if ZoneInfo is None:
        return date.today()
    return datetime.now(ZoneInfo("Asia/Dubai")).date()


def _clean_candidate(value: str) -> str:
    return re.split(r"\s*\(", value.strip(), maxsplit=1)[0].strip()


def _parse_date_with_formats(text: str) -> Optional[date]:
    cleaned = re.split(r"\s+\d{1,2}:\d{2}(?::\d{2})?", text, maxsplit=1)[0].strip().replace(",", "")
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    return None


def _parse_date_with_fallback(text: str) -> Optional[date]:
    cleaned = re.split(r"\s+\d{1,2}:\d{2}(?::\d{2})?", text, maxsplit=1)[0].strip().replace(",", "")
    extra_formats = (
        "%B %d %Y",
        "%b %d %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y %B %d",
        "%Y %b %d",
    )
    for date_format in extra_formats:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    return None


def parse_trade_license_expiry_date(value: Any) -> Optional[date]:
    text = ("" if value is None else str(value)).strip()
    if not text:
        return None
    candidates = [text, text.split("(", 1)[0].strip()]
    for candidate in candidates:
        if not candidate:
            continue
        parsed = _parse_date_with_formats(candidate)
        if parsed is not None:
            return parsed
    return _parse_date_with_fallback(text)


def extract_trade_license_expiry_date(text: str) -> Optional[date]:
    match = EXPIRY_PATTERN.search(text or "")
    if not match:
        return None
    return parse_trade_license_expiry_date(_clean_candidate(match.group(1)))


def classify_trade_license_expiry(text: str, today: Optional[date] = None, warning_days: int = 60) -> Optional[TradeLicenseExpiryDecision]:
    expiry_date = extract_trade_license_expiry_date(text)
    if not expiry_date:
        return None
    resolved_today = today or _today()
    days_remaining = (expiry_date - resolved_today).days
    status = "expired" if days_remaining < 0 else "renewal_due" if days_remaining <= warning_days else "valid"
    return TradeLicenseExpiryDecision(expiry_date=expiry_date, days_remaining=days_remaining, status=status)
