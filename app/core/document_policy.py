from dataclasses import dataclass
import os
from typing import Iterable


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw_value = _env(name, str(default))
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_list(name: str, default: Iterable[str]) -> tuple[str, ...]:
    raw_value = _env(name)
    if not raw_value:
        return tuple(default)
    values = [item.strip().lower() for item in raw_value.split(",")]
    return tuple(item for item in values if item)


DEFAULT_TRADE_ISSUING_AUTHORITY_ALLOWLIST = (
    "department of economy and tourism",
    "department of economic development",
    "economic development",
    "economy and tourism",
    "ded",
    "det",
    "added",
    "sedd",
    "ajman ded",
    "rakez",
    "dmcc",
    "jafza",
    "jebel ali free zone",
    "jebel ali free zone authority",
    "dafza",
    "dubai airport free zone",
    "ifza",
    "international free zone authority",
    "meydan free zone",
    "dubai south",
    "dtec",
    "dubai silicon oasis",
    "difc",
    "kizad",
    "kezad",
    "hamriyah free zone",
    "sharjah airport international free zone",
    "saif zone",
    "sharjah free zone",
    "fujairah free zone",
    "umm al quwain free trade zone",
    "uaq free trade zone",
    "ras al khaimah economic zone",
    "free zone authority",
    "free zone",
    "freezone",
)

DEFAULT_VAT_ISSUING_AUTHORITY_ALLOWLIST = (
    "federal tax authority",
    "fta",
)

DEFAULT_BANK_ISSUING_AUTHORITY_ALLOWLIST = (
    "bank",
    "branch",
    "financial institution",
)


@dataclass(frozen=True)
class DocumentPolicy:
    trade_vat_base_score: int = _env_int("DOCUMENT_ACCEPTANCE_TRADE_VAT_BASE_SCORE", 50)
    trade_vat_qr_score: int = _env_int("DOCUMENT_ACCEPTANCE_QR_SCORE", 10)
    trade_vat_verification_score: int = _env_int("DOCUMENT_ACCEPTANCE_VERIFICATION_SCORE", 10)
    trade_vat_logo_score: int = _env_int("DOCUMENT_ACCEPTANCE_LOGO_SCORE", 5)
    trade_vat_issuing_authority_score: int = _env_int("DOCUMENT_ACCEPTANCE_ISSUING_AUTHORITY_SCORE", 20)
    trade_vat_gpt_max_score: int = _env_int("DOCUMENT_ACCEPTANCE_GPT_MAX_SCORE", 5)
    bank_base_score: int = _env_int("DOCUMENT_ACCEPTANCE_BANK_BASE_SCORE", 75)
    bank_logo_score: int = _env_int("DOCUMENT_ACCEPTANCE_BANK_LOGO_SCORE", 10)
    bank_issuing_authority_score: int = _env_int("DOCUMENT_ACCEPTANCE_BANK_ISSUING_AUTHORITY_SCORE", 3)
    bank_gpt_max_score: int = _env_int("DOCUMENT_ACCEPTANCE_BANK_GPT_MAX_SCORE", 15)
    approved_threshold: int = _env_int("DOCUMENT_ACCEPTANCE_APPROVED_THRESHOLD", 91)
    review_threshold: int = _env_int("DOCUMENT_ACCEPTANCE_REVIEW_THRESHOLD", 81)
    trade_issuing_authority_allowlist: tuple[str, ...] = _env_list(
        "DOCUMENT_ACCEPTANCE_TRADE_ISSUING_AUTHORITY_ALLOWLIST",
        DEFAULT_TRADE_ISSUING_AUTHORITY_ALLOWLIST,
    )
    vat_issuing_authority_allowlist: tuple[str, ...] = _env_list(
        "DOCUMENT_ACCEPTANCE_VAT_ISSUING_AUTHORITY_ALLOWLIST",
        DEFAULT_VAT_ISSUING_AUTHORITY_ALLOWLIST,
    )
    bank_issuing_authority_allowlist: tuple[str, ...] = _env_list(
        "DOCUMENT_ACCEPTANCE_BANK_ISSUING_AUTHORITY_ALLOWLIST",
        DEFAULT_BANK_ISSUING_AUTHORITY_ALLOWLIST,
    )


settings = DocumentPolicy()


def trade_vat_base_score() -> int:
    return settings.trade_vat_base_score


def trade_vat_qr_score() -> int:
    return settings.trade_vat_qr_score


def trade_vat_verification_score() -> int:
    return settings.trade_vat_verification_score


def trade_vat_logo_score() -> int:
    return settings.trade_vat_logo_score


def trade_vat_issuing_authority_score() -> int:
    return settings.trade_vat_issuing_authority_score


def trade_vat_gpt_max_score() -> int:
    return settings.trade_vat_gpt_max_score


def bank_base_score() -> int:
    return settings.bank_base_score


def bank_logo_score() -> int:
    return settings.bank_logo_score


def bank_issuing_authority_score() -> int:
    return settings.bank_issuing_authority_score


def bank_gpt_max_score() -> int:
    return settings.bank_gpt_max_score


def approved_threshold() -> int:
    return settings.approved_threshold


def review_threshold() -> int:
    return settings.review_threshold


def trade_issuing_authority_allowlist() -> tuple[str, ...]:
    return settings.trade_issuing_authority_allowlist


def vat_issuing_authority_allowlist() -> tuple[str, ...]:
    return settings.vat_issuing_authority_allowlist


def bank_issuing_authority_allowlist() -> tuple[str, ...]:
    return settings.bank_issuing_authority_allowlist
