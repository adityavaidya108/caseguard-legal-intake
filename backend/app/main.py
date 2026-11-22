from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status

from backend.app import deadlines, vault
from backend.app.llm_claude import extract
from backend.app.pdf_reader import PdfValidationError, read_pdf
from backend.app.redactor import redact
from backend.app.schemas import ExtractResponse
from backend.app.security import PIIScrubFilter, require_api_key

logger = logging.getLogger(__name__)

_PII_FILTER_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def _attach_pii_scrub_filters() -> None:
    logging.basicConfig(level=logging.INFO)
    scrub = PIIScrubFilter()
    for name in _PII_FILTER_LOGGER_NAMES:
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(scrub)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _attach_pii_scrub_filters()
    yield


app = FastAPI(
    title="CaseGuard Legal Intake",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/extract",
    response_model=ExtractResponse,
    dependencies=[Depends(require_api_key)],
)
async def extract_notice(file: UploadFile = File(...)) -> ExtractResponse:
    try:
        data = await file.read()
        pdf = read_pdf(data, file.filename or "upload.pdf")
        redaction = redact(pdf.text)
        review_id = vault.save(redaction.vault)
        extraction = extract(redaction.redacted_text)
        deadline = deadlines.compute(extraction, today=date.today())
        return ExtractResponse(
            review_id=review_id,
            filename=pdf.filename,
            raw_text=pdf.text,
            redacted_text=redaction.redacted_text,
            redaction_counts=redaction.counts,
            extraction=extraction,
            deadline=deadline,
        )
    except PdfValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("extract failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from None
