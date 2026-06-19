from __future__ import annotations

import json
import re
from typing import Any, Optional


def _field_value(field_info: dict) -> Any:
    field_type = (field_info.get("type") or "").strip()
    if field_type:
        value_key = f"value{field_type[:1].upper()}{field_type[1:]}"
        value = field_info.get(value_key)
        if value not in (None, ""):
            return value

    for key in ("valueString", "valueDate", "valueNumber", "valueInteger", "valueBoolean", "valueArray", "valueObject", "content", "text"):
        value = field_info.get(key)
        if value not in (None, ""):
            return value

    return None


def _is_populated_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _candidate_field_blocks(data: dict) -> list[dict]:
    field_blocks: list[dict] = []
    for key in ("contents", "documents"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("fields"), dict):
                    field_blocks.append(item["fields"])
    fields = data.get("fields")
    if isinstance(fields, dict):
        field_blocks.append(fields)
    return field_blocks


def _candidate_names(field: str, alias_map: dict[str, list[str]]) -> list[str]:
    names: list[str] = []
    for candidate_name in [field] + list(alias_map.get(field, [])):
        if candidate_name not in names:
            names.append(candidate_name)
    return names


def _field_confidence(field_info: dict) -> float:
    confidence = field_info.get("confidence")
    return float(confidence) if isinstance(confidence, (int, float)) and float(confidence) > 0 else 0.0


def _best_field_info(candidate_blocks: list[dict], candidate_names: list[str]) -> dict[str, Any] | None:
    candidates = []
    for field_block in candidate_blocks:
        for candidate_name in candidate_names:
            field_info = field_block.get(candidate_name)
            if field_info:
                value = _field_value(field_info)
                if _is_populated_value(value):
                    candidates.append((_field_confidence(field_info), value, field_info.get("confidence")))
    if not candidates:
        return None
    confidence_score, value, confidence = max(candidates, key=lambda item: item[0])
    return {"value": value, "confidence": confidence if confidence_score > 0 else None}


def extract_fields_with_confidence(json_data: Any, target_fields: list[str], field_aliases: Optional[dict[str, list[str]]] = None) -> dict[str, dict[str, Any]]:
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    try:
        candidate_blocks = _candidate_field_blocks(data if isinstance(data, dict) else {})
        alias_map = field_aliases or {}
        extracted_data = {
            field: best_field_info
            for field in target_fields
            if (best_field_info := _best_field_info(candidate_blocks, _candidate_names(field, alias_map)))
        }
    except (IndexError, AttributeError, TypeError, ValueError):
        return {}
    return extracted_data


def score_from_results(results: dict[str, dict[str, Any]]) -> Optional[float]:
    confidences: list[float] = []
    for field_result in results.values():
        if not isinstance(field_result, dict):
            continue
        confidence = field_result.get("confidence")
        if isinstance(confidence, (int, float)) and float(confidence) > 0:
            confidences.append(float(confidence))

    if not confidences:
        return None

    return round(sum(confidences) / len(confidences), 4)
