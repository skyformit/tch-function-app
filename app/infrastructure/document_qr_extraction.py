from __future__ import annotations

import io
import re
from typing import Any

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None

from pypdf import PdfReader


def extract_qr_codes_from_pdf(file_bytes: bytes) -> list[str]:
    if not file_bytes:
        return []
    qr_codes: list[str] = []
    reader = _open_pdf_reader(file_bytes)
    if reader is not None:
        for page in reader.pages:
            qr_codes.extend(_extract_qr_codes_from_page(page))
        if not qr_codes:
            qr_codes.extend(_extract_urls_from_reader(reader))
    if not qr_codes:
        qr_codes.extend(_extract_qr_codes_from_rendered_pdf(file_bytes))
    return _unique_values(qr_codes)


def extract_verification_urls_from_pdf(file_bytes: bytes) -> list[str]:
    if not file_bytes:
        return []
    urls: list[str] = []
    reader = _open_pdf_reader(file_bytes)
    if reader is not None:
        for page in reader.pages:
            urls.extend(_extract_urls_from_text(_page_text(page)))
    if not urls:
        urls.extend(_extract_urls_from_qr_payloads(file_bytes))
    return _unique_values(urls)


def _open_pdf_reader(file_bytes: bytes) -> Any | None:
    if PdfReader is None:
        return None
    try:
        return PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return None


def _extract_qr_codes_from_page(page: Any) -> list[str]:
    resources = page.get("/Resources") if hasattr(page, "get") else None
    xobject = resources.get("/XObject") if resources else None
    if not xobject:
        return []
    try:
        xobject = xobject.get_object()
    except Exception:
        pass

    qr_codes: list[str] = []
    for _, obj in xobject.items():
        try:
            image_object = obj.get_object()
        except Exception:
            image_object = obj
        if image_object.get("/Subtype") != "/Image":
            continue
        qr_codes.extend(_decode_qr_from_image_bytes(_image_bytes(image_object)))
    return qr_codes


def _extract_qr_codes_from_rendered_pdf(file_bytes: bytes) -> list[str]:
    if fitz is None or Image is None or cv2 is None or np is None:
        return []
    try:
        document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return []

    qr_codes: list[str] = []
    for page_index in range(len(document)):
        try:
            page = document[page_index]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            qr_codes.extend(_decode_qr_from_image_array(np.array(image)))
        except Exception:
            continue
    return qr_codes


def _image_bytes(image_object: Any) -> bytes:
    try:
        return image_object.get_data()
    except Exception:
        return b""


def _decode_qr_from_image_bytes(image_bytes: bytes) -> list[str]:
    if not image_bytes or Image is None or cv2 is None or np is None:
        return []
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return _decode_qr_from_image_array(np.array(image))
    except Exception:
        return []


def _decode_qr_from_image_array(image_array: Any) -> list[str]:
    if cv2 is None or np is None:
        return []
    try:
        detector = cv2.QRCodeDetector()
        decoded_texts: list[str] = []
        try:
            retval, decoded_info, _, _ = detector.detectAndDecodeMulti(image_array)
            if retval and decoded_info:
                decoded_texts.extend([text.strip() for text in decoded_info if text and text.strip()])
        except Exception:
            pass
        if decoded_texts:
            return decoded_texts
        decoded_text, _, _ = detector.detectAndDecode(image_array)
        return [decoded_text.strip()] if decoded_text and decoded_text.strip() else []
    except Exception:
        return []


def _unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _extract_urls_from_reader(reader: Any) -> list[str]:
    urls: list[str] = []
    for page in getattr(reader, "pages", []):
        text = _page_text(page)
        urls.extend(_extract_urls_from_text(text))
    return urls


def _extract_urls_from_qr_payloads(file_bytes: bytes) -> list[str]:
    qr_payloads = extract_qr_codes_from_pdf(file_bytes)
    urls: list[str] = []
    for payload in qr_payloads:
        urls.extend(_extract_urls_from_text(payload))
    return urls


def _page_text(page: Any) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def _extract_urls_from_text(text: str) -> list[str]:
    if not text:
        return []
    patterns = [
        r"(https?://[^\s\]\)>'\"]+)",
        r"(?<!@)\b(www\.[^\s\]\)>'\"]+)",
    ]
    urls: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            url = _normalize_url(match)
            if url:
                urls.append(url)
    return urls


def _normalize_url(value: str) -> str:
    cleaned = value.strip().strip(".,;:!)]}>\"'")
    if cleaned.lower().startswith("www."):
        return f"https://{cleaned}"
    return cleaned
