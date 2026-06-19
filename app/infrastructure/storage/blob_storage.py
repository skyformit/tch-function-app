import mimetypes
import posixpath
import re
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from app.core.storage_config import storage_account_url, storage_connection_string, storage_prefix


def clean_name(value: Optional[str], fallback: str) -> str:
    cleaned = (value or "").strip().replace("\\", "/").lstrip("/")
    return cleaned or fallback


def document_type(value: Optional[str]) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned or "general"


def guess_content_type(file_name: str) -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def blob_service_client() -> BlobServiceClient:
    connection_string = storage_connection_string()
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)

    account_url = storage_account_url()
    if not account_url:
        raise RuntimeError("Missing env var: AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING")

    return BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())


def _ensure_container(container_client, ensure_container: bool) -> None:
    if not ensure_container:
        return
    try:
        container_client.create_container()
    except Exception:
        pass


def _upload_blob(container_client, blob_name: str, file_bytes: bytes, content_type: str, overwrite: bool) -> None:
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(file_bytes, overwrite=overwrite, content_settings=ContentSettings(content_type=content_type))


def _blob_result(container_name: str, blob_name: str, content_type: str, file_bytes: bytes) -> dict:
    return {
        "container": container_name,
        "blob_name": blob_name,
        "content_type": content_type,
        "size": len(file_bytes),
        "storage_account_url": storage_account_url() or None,
        "used_connection_string": bool(storage_connection_string()),
    }


def build_blob_name(
    file_name: str,
    *,
    document_type_name: Optional[str] = None,
    blob_name: Optional[str] = None,
    prefix: Optional[str] = None,
) -> str:
    resolved_prefix = storage_prefix() if prefix is None else (prefix or "")
    resolved_name = clean_name(blob_name, file_name)
    path_parts = [part for part in (resolved_prefix.strip("/"),) if part]
    if document_type_name is not None:
        path_parts.append(document_type(document_type_name))
    path_parts.append(resolved_name)
    return posixpath.join(*path_parts)


def upload_blob_bytes(*, container_name: str, file_name: str, file_bytes: bytes, document_type_name: Optional[str] = None, blob_name: Optional[str] = None, content_type: Optional[str] = None, overwrite: bool = True, ensure_container: bool = True) -> dict:
    resolved_blob_name = build_blob_name(
        file_name,
        document_type_name=document_type_name,
        blob_name=blob_name,
    )
    service_client = blob_service_client()
    container_client = service_client.get_container_client(container_name)
    _ensure_container(container_client, ensure_container)
    resolved_content_type = content_type or guess_content_type(file_name)
    _upload_blob(container_client, resolved_blob_name, file_bytes, resolved_content_type, overwrite)
    return _blob_result(container_name, resolved_blob_name, resolved_content_type, file_bytes)
