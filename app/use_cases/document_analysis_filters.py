from typing import Any, Callable, Optional


def _is_allowed_by_confidence(field_name: str, confidence: Optional[float], minimum_confidence: Optional[dict[str, float]]) -> bool:
    threshold = (minimum_confidence or {}).get(field_name)
    return threshold is None or (confidence is not None and confidence >= threshold)


def _is_allowed_by_validator(field_name: str, value: Any, validators: Optional[dict[str, Callable[[Any], bool]]]) -> bool:
    validator = (validators or {}).get(field_name)
    if validator is None:
        return True
    try:
        return bool(validator(value))
    except Exception:
        return False


def _filter_results(
    results: dict[str, dict[str, Any]],
    minimum_confidence: Optional[dict[str, float]] = None,
    validators: Optional[dict[str, Callable[[Any], bool]]] = None,
) -> dict[str, dict[str, Any]]:
    filtered: dict[str, dict[str, Any]] = {}
    for field_name, field_result in results.items():
        if _should_keep_field(field_name, field_result, minimum_confidence, validators):
            filtered[field_name] = field_result
    return filtered


def _should_keep_field(
    field_name: str,
    field_result: Any,
    minimum_confidence: Optional[dict[str, float]],
    validators: Optional[dict[str, Callable[[Any], bool]]],
) -> bool:
    if not isinstance(field_result, dict):
        return False
    value = field_result.get("value")
    if value in (None, "", [], {}):
        return False
    if not _is_allowed_by_confidence(field_name, field_result.get("confidence"), minimum_confidence):
        return False
    return _is_allowed_by_validator(field_name, value, validators)
