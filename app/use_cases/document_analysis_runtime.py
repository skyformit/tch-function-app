from dataclasses import dataclass
from typing import Any, Optional

from app.core.document_settings import (
    document_analysis_allow_analyze_without_upload,
    document_analysis_debug_raw_keys,
    document_analysis_provider,
)
from app.core.storage_config import storage_container
from app.domain.document_analysis.extraction import extract_fields_with_confidence, score_from_results
from app.infrastructure.external.content_understanding_client import analyze_document as analyze_with_content_understanding
from app.infrastructure.external.document_intelligence_client import analyze_document as analyze_with_document_intelligence
from app.infrastructure.storage.blob_storage import blob_service_client, build_blob_name, clean_name, guess_content_type


DEFAULT_TARGET_FIELD_ALIASES = {
    "LicenceActivities": ["LicenseActivities", "Licence Activities", "License Activities"],
}
DEFAULT_PROVIDER = "document_intelligence"
DEFAULT_DEBUG_RAW_KEYS = False


@dataclass
class AnalysisOutcome:
    provider: str
    raw_result: dict
    model_id: str
    api_version: str
    file_name: str
    container: str
    blob_name: str
    upload_skipped: bool


def _provider() -> str:
    raw_value = (document_analysis_provider() or DEFAULT_PROVIDER).strip().lower().replace("-", "_")
    if raw_value in {"document_intelligence", "document_intelligence_sdk", "di"}:
        return "document_intelligence"
    if raw_value in {"content_understanding", "content_understanding_sdk", "cu"}:
        return "content_understanding"
    return DEFAULT_PROVIDER


def _allow_analyze_without_upload() -> bool:
    return document_analysis_allow_analyze_without_upload()


def _debug_raw_keys_enabled() -> bool:
    return document_analysis_debug_raw_keys()


def _collect_field_keys_from_block(raw_result: dict, keys: set[str]) -> None:
    for container_key in ("contents", "documents"):
        blocks = raw_result.get(container_key)
        if not isinstance(blocks, list):
            continue
        for item in blocks:
            if isinstance(item, dict) and isinstance(item.get("fields"), dict):
                keys.update(item["fields"].keys())

    fields = raw_result.get("fields")
    if isinstance(fields, dict):
        keys.update(fields.keys())


def _collect_raw_field_keys(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        return {"top_level_keys": [], "field_keys": []}

    field_keys: set[str] = set()
    _collect_field_keys_from_block(raw_result, field_keys)
    return {"top_level_keys": sorted(raw_result.keys()), "field_keys": sorted(field_keys)}


def _upload_file(file_name: str, file_bytes: bytes, content_type: Optional[str]) -> tuple[str, str]:
    resolved_container = storage_container()
    upload_name = build_blob_name(file_name)
    resolved_content_type = content_type or guess_content_type(file_name)
    service_client = blob_service_client()
    container_client = service_client.get_container_client(resolved_container)
    try:
        container_client.create_container()
    except Exception:
        pass
    from azure.storage.blob import ContentSettings

    blob_client = container_client.get_blob_client(upload_name)
    blob_client.upload_blob(file_bytes, overwrite=True, content_settings=ContentSettings(content_type=resolved_content_type))
    return resolved_container, upload_name


def analyze_trade_license_document(
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str],
    target_fields: list[str],
    query_fields: Optional[list[str]] = None,
) -> AnalysisOutcome:
    provider = _provider()
    resolved_container, upload_name, upload_skipped = _resolve_upload(file_name, file_bytes, content_type)
    resolved_content_type = content_type or guess_content_type(file_name)
    raw_result, model_id, api_version = _analyze_by_provider(provider, file_bytes, resolved_content_type, query_fields or target_fields)
    return AnalysisOutcome(provider, raw_result, model_id, api_version, file_name, resolved_container, upload_name, upload_skipped)


def _resolve_upload(file_name: str, file_bytes: bytes, content_type: Optional[str]) -> tuple[str, str, bool]:
    if _allow_analyze_without_upload():
        return storage_container(), build_blob_name(file_name), True
    resolved_container, upload_name = _upload_file(file_name, file_bytes, content_type)
    return resolved_container, upload_name, False


def _analyze_by_provider(provider: str, file_bytes: bytes, content_type: str, query_fields: list[str]) -> tuple[dict, str, str]:
    if provider == "content_understanding":
        return analyze_with_content_understanding(file_bytes, content_type)
    return analyze_with_document_intelligence(file_bytes, content_type, query_fields=query_fields)


def build_trade_license_results(outcome: AnalysisOutcome, target_fields: list[str]) -> dict[str, dict[str, Any]]:
    return extract_fields_with_confidence(
        outcome.raw_result,
        target_fields,
        field_aliases=DEFAULT_TARGET_FIELD_ALIASES,
    )


def score_results(results: dict[str, dict[str, Any]]) -> Optional[float]:
    return score_from_results(results)
