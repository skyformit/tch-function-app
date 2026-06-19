from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover - dependency may be absent in some local envs
    AzureOpenAI = None

from app.core.document_settings import (
    document_review_openai_api_key,
    document_review_openai_api_version,
    document_review_openai_deployment_name,
    document_review_openai_endpoint,
)


def extract_qr_codes(json_data: Any) -> list[str]:
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    qr_values: list[str] = []
    _scan_qr_values(data, qr_values)
    return qr_values


def _scan_qr_values(value: Any, qr_values: list[str]) -> None:
    if isinstance(value, dict):
        _collect_qr_from_barcodes(value, qr_values)
        for item in value.values():
            _scan_qr_values(item, qr_values)
    elif isinstance(value, list):
        for item in value:
            _scan_qr_values(item, qr_values)


def _collect_qr_from_barcodes(value: dict, qr_values: list[str]) -> None:
    for barcode in value.get("barcodes", []):
        if not isinstance(barcode, dict):
            continue
        kind = str(barcode.get("kind") or "")
        decoded_value = barcode.get("value")
        if "qr" in kind.lower() and decoded_value and decoded_value not in qr_values:
            qr_values.append(decoded_value)


def build_qr_codes_result(raw_result: Any) -> dict[str, Any]:
    qr_codes = extract_qr_codes(raw_result)
    return {"value": qr_codes or None, "confidence": 0.95 if qr_codes else 0.0}


def review_with_azure_openai(extracted_fields: dict[str, Any], deployment_name: Optional[str] = None) -> dict[str, Any]:
    if AzureOpenAI is None:
        return _review_unavailable("openai package is not installed")
    endpoint = document_review_openai_endpoint()
    api_key = document_review_openai_api_key()
    deployment = (deployment_name or document_review_openai_deployment_name() or "").strip()
    if not endpoint or not deployment:
        return _review_unavailable("Missing review configuration")
    try:
        client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=document_review_openai_api_version())
        raw_text = _review_text(client, extracted_fields, deployment)
        return _parse_review(raw_text)
    except Exception as exc:
        logging.error("Azure OpenAI review failed: %s", exc)
        return _review_failed(str(exc))


def _review_text(client: AzureOpenAI, extracted_fields: dict[str, Any], deployment: str) -> str:
    response = client.chat.completions.create(model=deployment, messages=_review_messages(extracted_fields), temperature=0, max_tokens=600)
    return (response.choices[0].message.content or "").strip()


def _review_messages(extracted_fields: dict[str, Any]) -> list[dict[str, str]]:
    return [{"role": "system", "content": _review_system_prompt()}, {"role": "user", "content": f"Extracted fields:\n{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}"}]


def _review_system_prompt() -> str:
    return (
        "You are a document fraud-review assistant. Review extracted fields for internal inconsistencies, "
        "implausible values, placeholder/test data, date logic errors, formatting that looks machine-altered, "
        "or anything that suggests the document is fake, templated, or tampered with. Respond with ONLY a JSON "
        "object in this exact shape: {\"is_consistent\": true|false, \"anomalies\": [\"...\"], \"plausibility_score\": 0.0-1.0, \"reasoning\": \"short explanation\"}."
    )


def _parse_review(raw_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _review_failed(raw_text)


def _review_failed(reasoning: str) -> dict[str, Any]:
    return {"is_consistent": False, "anomalies": ["Could not parse GPT review output."], "plausibility_score": 0.0, "reasoning": reasoning}


def _review_unavailable(reasoning: str) -> dict[str, Any]:
    return {"is_consistent": False, "anomalies": [reasoning], "plausibility_score": 0.0, "reasoning": reasoning, "skipped": True}


def build_trade_license_extras(raw_result: Any, extracted_fields: dict[str, Any]) -> dict[str, Any]:
    extras = {"qr_codes": build_qr_codes_result(raw_result)}
    gpt_review = review_with_azure_openai(extracted_fields)
    if not gpt_review.get("skipped"):
        extras["gpt_review"] = gpt_review
    return extras
