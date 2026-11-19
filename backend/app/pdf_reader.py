from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from backend.app.config import get_settings

_BLANK_LINES_RE = re.compile(r"\n{3,}")


class PdfValidationError(Exception):
    """Raised when an uploaded PDF fails validation."""


@dataclass(frozen=True)
class PdfText:
    filename: str
    page_count: int
    text: str


def read_pdf(data: bytes, filename: str) -> PdfText:
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    safe_name = Path(filename).name

    if len(data) == 0 or len(data) > max_bytes:
        raise PdfValidationError(
            f"PDF exceeds maximum size of {settings.max_upload_mb} MB"
            if len(data) > max_bytes
            else "PDF is empty"
        )
    if not data.startswith(b"%PDF"):
        raise PdfValidationError("File is not a valid PDF")

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            if page_count > settings.max_pdf_pages:
                raise PdfValidationError(
                    f"PDF exceeds maximum of {settings.max_pdf_pages} pages"
                )
            page_texts = [(page.extract_text() or "") for page in pdf.pages]
    except PdfValidationError:
        raise
    except Exception:
        raise PdfValidationError(
            "Could not read PDF (corrupt or password-protected)"
        ) from None

    raw = "\n".join(page_texts)
    lines = [line for line in raw.splitlines() if "SPECIMEN" not in line]
    text = "\n".join(lines)
    text = _BLANK_LINES_RE.sub("\n\n", text).strip()

    if len(text) < 50:
        raise PdfValidationError(
            "No readable text found. Scanned/image PDFs are not supported yet"
        )

    return PdfText(filename=safe_name, page_count=page_count, text=text)
