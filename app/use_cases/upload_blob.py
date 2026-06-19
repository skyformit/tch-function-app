import base64
import json
from typing import Optional

import azure.functions as func

from app.core.config import settings
from app.infrastructure.external.foundry.common import _with_response_metadata
from app.infrastructure.storage.blob_storage import clean_name, document_type, upload_blob_bytes
from core.foundry import _json_response


def _bad_request(message: str) -> func.HttpResponse:
    return _json_response({"ok": False, "error": {"code": "bad_request", "message": message}}, status_code=400)


def _missing_config(name: str) -> func.HttpResponse:
    return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}, status_code=500)


def _empty_upload_error() -> func.HttpResponse:
    return _bad_request("Uploaded file is empty")


def _as_bytes_from_json(body: dict, upload_content_type: Optional[str]):
    if body.get("content_base64"):
        try:
            return base64.b64decode(body["content_base64"]), upload_content_type
        except Exception:
            return _bad_request("content_base64 is not valid base64")
    if body.get("content") is None:
        return _bad_request("Provide multipart file upload or JSON with file_name and content_base64/content")
    content_value = body["content"]
    if isinstance(content_value, str):
        return content_value.encode("utf-8"), upload_content_type or "text/plain; charset=utf-8"
    return json.dumps(content_value, ensure_ascii=False).encode("utf-8"), upload_content_type or "application/json"


def _response_payload(
    *,
    file_name: str,
    resolved_document_type: Optional[str],
    payload: bytes,
    upload_content_type: Optional[str],
    blob_name: Optional[str],
    overwrite: bool,
) -> dict:
    result = _upload_result(file_name, resolved_document_type, payload, upload_content_type, blob_name, overwrite)
    return _with_success_metadata(result, file_name, resolved_document_type)


def _upload_result(
    file_name: str,
    resolved_document_type: Optional[str],
    payload: bytes,
    upload_content_type: Optional[str],
    blob_name: Optional[str],
    overwrite: bool,
) -> dict:
    return upload_blob_bytes(container_name=settings.azure_storage_container, file_name=file_name, file_bytes=payload, document_type_name=resolved_document_type, blob_name=blob_name if isinstance(blob_name, str) else None, content_type=upload_content_type, overwrite=overwrite, ensure_container=True)


def _with_success_metadata(result: dict, file_name: str, resolved_document_type: Optional[str]) -> dict:
    return _with_response_metadata({
        **result,
        "ok": True,
        "file_name": file_name,
        "document_type": document_type(resolved_document_type if isinstance(resolved_document_type, str) else None),
    }, "storage")


def _request_content_type(req) -> str:
    return (req.headers.get("content-type") or "").lower()


async def _multipart_payload(req):
    form = await req.form()
    uploaded_file = form.get("file") or form.get("upload")
    if uploaded_file is None:
        return _bad_request("Provide a multipart file field named 'file' or 'upload'")
    file_name = clean_name(getattr(uploaded_file, "filename", None), "upload.bin")
    resolved_document_type = form.get("document_type") or form.get("type")
    blob_name = form.get("blob_name")
    overwrite = str(form.get("overwrite", "")).strip().lower() in {"1", "true", "yes", "on"}
    upload_content_type = getattr(uploaded_file, "content_type", None)
    payload = await uploaded_file.read()
    return uploaded_file, file_name, resolved_document_type, blob_name, overwrite, upload_content_type, payload


async def _json_payload(req):
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    file_name, resolved_document_type, blob_name, overwrite, upload_content_type = _json_fields(body)
    json_result = _as_bytes_from_json(body, upload_content_type)
    if isinstance(json_result, func.HttpResponse):
        return json_result
    payload, upload_content_type = json_result
    return file_name, resolved_document_type, blob_name, overwrite, upload_content_type, payload


def _json_fields(body: dict):
    return (
        clean_name(body.get("file_name"), "upload.bin"),
        body.get("document_type") or body.get("type"),
        body.get("blob_name"),
        bool(body.get("overwrite")),
        body.get("content_type"),
    )


async def upload_blob(req) -> func.HttpResponse:
    try:
        request_result = await _resolve_request(req)
        if isinstance(request_result, func.HttpResponse):
            return request_result
        file_name, resolved_document_type, blob_name, overwrite, upload_content_type, payload = request_result
        if not settings.azure_storage_container:
            return _missing_config("AZURE_STORAGE_CONTAINER")
        return _json_response(_response_payload(file_name=file_name, resolved_document_type=resolved_document_type, payload=payload, upload_content_type=upload_content_type, blob_name=blob_name, overwrite=overwrite), status_code=200)
    except Exception as exc:
        return _json_response({"ok": False, "error": {"code": "upload_error", "message": str(exc)}}, status_code=500)


async def _resolve_request(req):
    if "multipart/form-data" in _request_content_type(req):
        multipart_result = await _multipart_payload(req)
        if isinstance(multipart_result, func.HttpResponse):
            return multipart_result
        _, file_name, resolved_document_type, blob_name, overwrite, upload_content_type, payload = multipart_result
        return file_name, resolved_document_type, blob_name, overwrite, upload_content_type, payload
    return await _json_payload(req)
