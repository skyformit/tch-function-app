import io
import re
from typing import Optional

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optional fallback
    PdfReader = None


BANK_ACCOUNT_PATTERNS = [
    r"(?:our\s+)?customer\s+(.+?)\s+has\s+maintained",
    r"(?:our\s+)?customer\s+(.+?)\s+holds?\s+(?:the\s+)?account",
    r"(?:our\s+)?customer\s+(.+?)\s+maintains?\s+(?:the\s+)?account",
    r"account\s+name\s*[:\-]?\s*(.+)",
    r"name\s+of\s+account\s+holder\s*[:\-]?\s*(.+)",
    r"account\s+holder\s*[:\-]?\s*(.+)",
    r"account\s+title\s*[:\-]?\s*(.+)",
    r"customer\s+name\s*[:\-]?\s*(.+)",
    r"account\s+owner\s*[:\-]?\s*(.+)",
    r"beneficiary\s+name\s*[:\-]?\s*(.+)",
    r"the\s+account\s+of\s+(.+?)\s+(?:is|was|has)\b",
    r"held\s+in\s+the\s+name\s+of\s+(.+?)(?:\s+(?:account|iban|swift|with|has|since|number)\b|[.,;])",
    r"in\s+the\s+name\s+of\s+(.+?)(?:\s+(?:account|iban|swift|with|has|since|number)\b|[.,;])",
    r"customer\s+name\s+is\s+(.+?)(?:[.,;]|\s+(?:account|iban|swift)\b)",
    r"account\s+name\s+of\s+customer\s*[:\-]?\s*(.+)",
]


def _extract_pdf_text(file_bytes: bytes) -> str:
    if PdfReader is None:
        return ""

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return ""

    return _reader_text(reader)


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def _reader_text(reader) -> str:
    text_parts: list[str] = []
    try:
        for page in reader.pages:
            text_parts.append(_page_text(page))
    except Exception:
        return ""
    return "\n".join(text_parts)


def _search_patterns(text: str, patterns: list[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _clean_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-,:;.") 


def _extract_candidate(text: str, patterns: list[str]) -> Optional[str]:
    candidate = _search_patterns(text, patterns)
    return _clean_candidate(candidate) if candidate else None


def extract_tax_registration_number_from_pdf(file_bytes: bytes) -> Optional[str]:
    text = _extract_pdf_text(file_bytes)
    if not text:
        return None

    candidate = _search_patterns(
        text,
        [
        r"Tax\s*Registration\s*Number\s*[:\-]?\s*([0-9]{15})",
        r"TaxRegistrationNumber\s*[:\-]?\s*([0-9]{15})",
        r"\bTRN\s*[:\-]?\s*([0-9]{15})",
        r"\b([0-9]{15})\b",
        ],
    )
    return candidate


def extract_bank_account_name_from_pdf(file_bytes: bytes) -> Optional[str]:
    text = _extract_pdf_text(file_bytes)
    return _extract_candidate(text, BANK_ACCOUNT_PATTERNS) if text else None
