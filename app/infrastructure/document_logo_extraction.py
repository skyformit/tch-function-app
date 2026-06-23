from __future__ import annotations

from typing import Any

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None


def extract_logo_presence_from_pdf(file_bytes: bytes) -> bool:
    if not file_bytes or fitz is None:
        return False
    try:
        document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return False
    if len(document) == 0:
        return False
    try:
        for page in document:
            if _page_has_top_image(page) or _page_has_any_image(page):
                return True
    except Exception:
        return False
    return False


def _page_has_top_image(page: Any) -> bool:
    page_height = float(page.rect.height or 0)
    if page_height <= 0:
        return False
    top_threshold = page_height * 0.3
    try:
        images = page.get_images(full=True) or []
    except Exception:
        return False
    for image_info in images:
        xref = image_info[0]
        try:
            rects = page.get_image_rects(xref) or []
        except Exception:
            rects = []
        for rect in rects:
            if float(rect.y1) <= top_threshold:
                return True
    return False


def _page_has_any_image(page: Any) -> bool:
    try:
        images = page.get_images(full=True) or []
    except Exception:
        return False
    return bool(images)
