from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.core.config import company_name_trailing_suffixes


@dataclass(frozen=True)
class CompanyNameComparison:
    string1: str
    string2: str
    normalized1: str
    normalized2: str
    exact_match: bool
    similarity_percent: float


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_company_name(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    cleaned = re.sub(r"[()\[\]{}.,;:/\\\-]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return text
    original_tokens = cleaned.split()
    normalized_tokens = [token.lower() for token in original_tokens]
    suffix_sequences = [
        ("limited", "liability", "company"),
        ("company", "limited"),
        ("sole", "proprietorship"),
        ("sole", "proprietor"),
        ("proprietorship",),
        ("establishment",),
        ("branch",),
        ("llc",),
        ("l", "l", "c"),
        ("fze",),
        ("fzc",),
        ("pjsc",),
        ("limited",),
        ("ltd",),
        ("co",),
        ("company",),
        ("est",),
    ] + [(suffix,) for suffix in company_name_trailing_suffixes() if " " not in suffix and suffix not in {"llc", "l.l.c", "co.", "co", "company", "ltd", "fze", "fzc", "pjsc"}]
    while normalized_tokens:
        matched = False
        for suffix in suffix_sequences:
            if len(normalized_tokens) >= len(suffix) and tuple(normalized_tokens[-len(suffix):]) == suffix:
                normalized_tokens = normalized_tokens[:-len(suffix)]
                matched = True
                break
        if not matched:
            break
    if not normalized_tokens:
        return ""
    candidate = " ".join(original_tokens[: len(normalized_tokens)]).strip()
    return _normalize_text(candidate)


def compare_company_names(a: Any, b: Any, case_sensitive: bool = False) -> CompanyNameComparison:
    raw_a = _normalize_text(a)
    raw_b = _normalize_text(b)
    normalized_a = normalize_company_name(raw_a)
    normalized_b = normalize_company_name(raw_b)

    s1 = normalized_a
    s2 = normalized_b
    if not case_sensitive:
        s1 = s1.lower()
        s2 = s2.lower()

    exact_match = bool(s1 and s1 == s2)
    if exact_match:
        return CompanyNameComparison(raw_a, raw_b, normalized_a, normalized_b, True, 100.0)

    similarity = SequenceMatcher(None, s1, s2).ratio() if s1 or s2 else 0.0
    return CompanyNameComparison(raw_a, raw_b, normalized_a, normalized_b, False, round(similarity * 100, 2))
