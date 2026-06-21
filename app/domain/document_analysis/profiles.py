import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


def _normalize_text(value: Any) -> str:
    return ("" if value is None else str(value)).strip()


def _normalize_upper(value: Any) -> str:
    return _normalize_text(value).replace(" ", "").replace("-", "").upper()


def _is_letters_spaces_punct(value: Any) -> bool:
    text = _normalize_text(value)
    return bool(text) and not any(char.isdigit() for char in text)


def _is_english_text(value: Any) -> bool:
    text = _normalize_text(value)
    return bool(text) and not _contains_arabic_letters(text) and bool(re.search(r"[A-Za-z]", text))


def _normalize_alpha_text(value: Any) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[^A-Za-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_entity_text(value: Any) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[^A-Za-z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _contains_arabic_letters(value: Any) -> bool:
    text = _normalize_text(value)
    return bool(re.search(r"[\u0600-\u06FF]", text))


def _is_digits_only(value: Any, min_length: int = 1, max_length: int = 30) -> bool:
    text = re.sub(r"\s+", "", _normalize_text(value))
    return text.isdigit() and min_length <= len(text) <= max_length


def _is_iban(value: Any) -> bool:
    text = re.sub(r"[\s-]+", "", _normalize_upper(value))
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", text))


def _is_swift(value: Any) -> bool:
    text = re.sub(r"[\s-]+", "", _normalize_upper(value))
    return bool(re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", text))


def _is_tax_registration_number(value: Any) -> bool:
    text = re.sub(r"[\s-]+", "", _normalize_text(value))
    return bool(re.fullmatch(r"\d{15}", text))


def _is_total_area(value: Any) -> bool:
    text = _normalize_text(value)
    return bool(re.fullmatch(r"\d+(\.\d+)?", text.replace(",", "")))


def _is_parcel_id(value: Any) -> bool:
    text = _normalize_text(value)
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-\/]{1,40}", text))


_UAE_LOCATION_ONLY_VALUES = {
    "abu dhabi",
    "dubai",
    "sharjah",
    "ajman",
    "fujairah",
    "ras al khaimah",
    "ras al khaymah",
    "umm al quwain",
    "uaq",
    "uae",
    "united arab emirates",
}

_LEGAL_SUFFIX_ONLY_VALUES = {
    "llc",
    "l l c",
    "l.l.c",
    "l.l.c.",
    "fze",
    "fzc",
    "pjsc",
    "ltd",
    "co",
    "company",
    "sole proprietorship",
    "sole proprietor",
    "est",
    "establishment",
    "branch",
}


def _is_location_only(value: Any) -> bool:
    return _normalize_alpha_text(value) in _UAE_LOCATION_ONLY_VALUES


def _is_legal_suffix_only(value: Any) -> bool:
    return _normalize_alpha_text(value) in _LEGAL_SUFFIX_ONLY_VALUES


def _is_legal_entity_suffix(value: Any) -> bool:
    text = _normalize_entity_text(value)
    if not text:
        return False
    suffix_patterns = [
        r"^(sole proprietorship|sole proprietor|proprietorship|establishment|branch)$",
        r"^(sole proprietorship\s+)?(llc|l l c|fze|fzc|pjsc|ltd|co|company|est|establishment|branch)$",
        r"^(limited liability company|sole proprietorship company)$",
    ]
    return any(re.fullmatch(pattern, text) for pattern in suffix_patterns)


def _looks_like_trade_name(value: Any) -> bool:
    text = _normalize_text(value)
    if not _is_english_text(text):
        return False
    if _is_location_only(text) or _is_legal_suffix_only(text):
        return False
    return True


def _looks_like_business_name(value: Any) -> bool:
    text = _normalize_text(value)
    if not _is_english_text(text):
        return False
    if _is_location_only(text) or _is_legal_suffix_only(text):
        return False
    return True


def _normalize_trade_name_value(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return text
    parts = re.split(r"\s*[-–—]\s*", text, maxsplit=1)
    if len(parts) == 2 and (_is_legal_suffix_only(parts[1]) or _is_legal_entity_suffix(parts[1])):
        return parts[0].strip()
    return text


Validator = Callable[[Any], bool]


@dataclass(frozen=True)
class DocumentAnalysisProfile:
    route_name: str
    response_fields: List[str]
    query_field_aliases: Dict[str, List[str]] = field(default_factory=dict)
    minimum_confidence: Dict[str, float] = field(default_factory=dict)
    validators: Dict[str, Validator] = field(default_factory=dict)
    failure_message: str = "No target fields were extracted"

    @property
    def query_fields(self) -> List[str]:
        names: List[str] = []
        for field_name in self.response_fields:
            aliases = [field_name] + list(self.query_field_aliases.get(field_name, []))
            for alias in aliases:
                normalized_alias = _normalize_text(alias)
                if not normalized_alias:
                    continue
                if not re.fullmatch(r"[\w]{1,64}", normalized_alias):
                    continue
                if normalized_alias not in names:
                    names.append(normalized_alias)
        return names[:20]

    def normalize_field_value(self, field_name: str, value: Any) -> Any:
        if field_name in {"CompanyName", "TradeName", "TradeNameEnglish", "OperatingName", "BusinessName"}:
            return _normalize_trade_name_value(value)
        return value


TRADE_LICENSE_PROFILE = DocumentAnalysisProfile(
    route_name="ValidateTradeLicense",
    response_fields=[
        "LicenseNumber",
        "LicenseNo",
        "LicenceNo",
        "LicenceNumber",
        "UnifiedRegistrationNo",
        "UnifiedLicenceNo",
        "LicenceActivities",
        "CompanyName",
        "TradeName",
        "TradeNameEnglish",
        "OperatingName",
        "BusinessName",
        "IssueDate",
        "ExpiryDate",
        "OfficialEmail",
        "OfficialMobile",
    ],
    query_field_aliases={
        "LicenceActivities": ["LicenseActivities", "Licence Activities", "License Activities"],
        "UnifiedRegistrationNo": ["UnifiedRegistrationNo", "UnifiedRegistration", "RegistrationNo"],
        "UnifiedLicenceNo": ["UnifiedLicenceNo", "UnifiedLicenseNo", "UnifiedLicence"],
        "CompanyName": ["Company Name", "Company", "LegalNameEnglish"],
        "IssueDate": ["IssuanceDate"],
        "OfficialEmail": ["Email"],
        "OfficialMobile": ["Mobile", "Phone"],
    },
    validators={
        "CompanyName": _is_english_text,
        "TradeNameEnglish": _looks_like_trade_name,
        "OperatingName": _is_english_text,
        "BusinessName": _looks_like_business_name,
    },
)

VAT_PROFILE = DocumentAnalysisProfile(
    route_name="ValidateVAT",
    response_fields=[
        "TaxRegistrationNumber",
        "LegalNameArabic",
        "LegalNameEnglish",
    ],
    query_field_aliases={
        "TaxRegistrationNumber": ["TaxRegistrationNo", "TRN", "VATNumber", "VATRegistrationNumber"],
        "LegalNameArabic": ["ArabicName"],
        "LegalNameEnglish": ["EnglishName", "LegalName"],
    },
    minimum_confidence={
        "TaxRegistrationNumber": 0.75,
        "LegalNameArabic": 0.7,
        "LegalNameEnglish": 0.65,
    },
    validators={
        "TaxRegistrationNumber": _is_tax_registration_number,
        "LegalNameArabic": _contains_arabic_letters,
        "LegalNameEnglish": _is_english_text,
    },
    failure_message="No target VAT fields were extracted",
)

BANK_PROFILE = DocumentAnalysisProfile(
    route_name="ValidateBankDocument",
    response_fields=[
        "BankName",
        "AccountName",
        "AccountNumber",
        "IBAN",
        "SwiftCode",
        "Branch",
    ],
    query_field_aliases={
        "BankName": ["Bank", "NameOfBank", "FinancialInstitution"],
        "AccountName": ["CustomerName", "AccountHolderName", "AccountHolder", "AccountTitle", "BeneficiaryName"],
        "AccountNumber": ["AccountNo", "AccountNo1", "AccountNum"],
        "IBAN": ["IBANNumber", "InternationalBankAccountNumber"],
        "SwiftCode": ["SWIFT", "Swift", "BIC", "BICCode"],
        "Branch": ["BranchName", "BankBranch"],
    },
    minimum_confidence={
        "BankName": 0.55,
        "AccountName": 0.6,
        "AccountNumber": 0.65,
        "IBAN": 0.7,
        "SwiftCode": 0.7,
        "Branch": 0.55,
    },
    validators={
        "BankName": _is_english_text,
        "AccountName": _is_english_text,
        "AccountNumber": lambda value: _is_digits_only(value, min_length=6, max_length=20),
        "IBAN": _is_iban,
        "SwiftCode": _is_swift,
        "Branch": _is_english_text,
    },
    failure_message="No target bank fields were extracted",
)

AFFECTION_PLAN_PROFILE = DocumentAnalysisProfile(
    route_name="ValidateAffectionPlan",
    response_fields=[
        "ParcelId",
        "TotalArea",
    ],
    query_field_aliases={
        "ParcelId": ["ParcelNo", "PlotNumber", "PlotNo"],
        "TotalArea": ["Area", "LandArea", "PlotArea"],
    },
    minimum_confidence={
        "ParcelId": 0.6,
        "TotalArea": 0.6,
    },
    validators={
        "ParcelId": _is_parcel_id,
        "TotalArea": _is_total_area,
    },
    failure_message="No target affection plan fields were extracted",
)
