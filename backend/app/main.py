from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status

from backend.app import deadlines, vault
from backend.app.audit import log_event
from backend.app.hubspot import HubSpotError, create_note, create_task, upsert_contact, upsert_deal
from backend.app.llm_claude import extract
from backend.app.pdf_reader import PdfValidationError, read_pdf
from backend.app.redactor import redact
from backend.app.schemas import (
    ApproveRequest,
    ApproveResponse,
    ExtractionResult,
    ExtractResponse,
)
from backend.app.security import PIIScrubFilter, require_api_key

logger = logging.getLogger(__name__)

_PII_FILTER_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
_TOKEN_RE = re.compile(r"\[[A-Z0-9_]+\]")


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


def rehydrate(text: str, real: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        value = real.get(token)
        return value if isinstance(value, str) else token

    return _TOKEN_RE.sub(repl, text)


def _rehydrate_extraction(
    extraction: ExtractionResult,
    real: dict[str, Any],
) -> ExtractionResult:
    data = extraction.model_dump(mode="json")
    for key, value in data.items():
        if isinstance(value, str):
            data[key] = rehydrate(value, real)
        elif isinstance(value, list):
            data[key] = [
                rehydrate(item, real) if isinstance(item, str) else item for item in value
            ]
    return ExtractionResult.model_validate(data)


def _split_client_name(raw: str) -> tuple[str, str]:
    if "," not in raw:
        parts = raw.split()
        if len(parts) >= 2:
            return " ".join(parts[:-1]).title(), parts[-1].title()
        return raw.title(), raw.title()
    last, rest = raw.split(",", 1)
    return rest.strip().title(), last.strip().title()


def _hubspot_priority(urgency: str) -> str:
    if urgency in ("CRITICAL", "HIGH"):
        return "HIGH"
    if urgency == "LOW":
        return "LOW"
    return "MEDIUM"


def _task_subject(extraction: ExtractionResult) -> str:
    if extraction.hearing_date is None:
        return "Review notice"
    hearing_type = (extraction.hearing_type or "").strip()
    if hearing_type:
        return f"Prepare for {hearing_type} hearing on {extraction.hearing_date}"
    return f"Prepare for hearing on {extraction.hearing_date}"


def _task_body(extraction: ExtractionResult, flags: list[str]) -> str:
    lines = [
        f"Hearing date: {extraction.hearing_date or 'n/a'}",
        f"Hearing time: {extraction.hearing_time or 'n/a'}",
        f"Hearing type: {extraction.hearing_type or 'n/a'}",
        f"Detained: {'yes' if extraction.is_detained else 'no'}",
    ]
    if flags:
        lines.append(f"Flags: {'; '.join(flags)}")
    if extraction.missing_docs:
        lines.append(f"Missing docs: {', '.join(extraction.missing_docs)}")
    return "\n".join(lines)


def _note_body(
    reviewer: str,
    urgency: str,
    previous_hearing_date: date | None,
    email_text: str,
) -> str:
    lines = [
        f"Approved by {reviewer}.",
        f"Urgency: {urgency}",
    ]
    if previous_hearing_date is not None:
        lines.append(f"Previous hearing date: {previous_hearing_date}")
    lines.extend(["", "Draft client email (not sent):", email_text])
    return "\n".join(lines)


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
        log_event(
            review_id,
            "extracted",
            doc_type=extraction.doc_type,
            redaction_counts=redaction.counts,
            urgency=deadline.urgency,
        )
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


@app.post(
    "/approve-and-sync",
    response_model=ApproveResponse,
    dependencies=[Depends(require_api_key)],
)
async def approve_and_sync(body: ApproveRequest) -> ApproveResponse:
    review_id = str(body.review_id)
    real = vault.get(review_id)
    if real is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review expired. Please upload the document again.",
        )

    log_event(
        review_id,
        "approved",
        reviewer=body.reviewer,
        urgency=body.deadline.urgency,
    )

    try:
        hydrated = _rehydrate_extraction(body.extraction, real)
        client_name = real.get("[CLIENT_NAME_1]")
        a_number = real.get("[A_NUMBER_1]")
        if not isinstance(client_name, str) or not isinstance(a_number, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Required client identifiers missing from vault.",
            )

        first_name, last_name = _split_client_name(client_name)
        contact_id = upsert_contact(first_name, last_name, a_number)
        deal_id = upsert_deal(f"{last_name} - {hydrated.matter_type}", contact_id)

        due = body.deadline.task_due_date or date.today()
        task_id = create_task(
            subject=_task_subject(hydrated),
            body=_task_body(hydrated, body.deadline.flags),
            due_date=due,
            priority=_hubspot_priority(body.deadline.urgency),
            contact_id=contact_id,
            deal_id=deal_id,
        )
        note_id = create_note(
            body=_note_body(
                body.reviewer,
                body.deadline.urgency,
                hydrated.previous_hearing_date,
                hydrated.draft_client_email,
            ),
            contact_id=contact_id,
            deal_id=deal_id,
        )
        vault.delete(review_id)
        audit_id = log_event(
            review_id,
            "synced",
            reviewer=body.reviewer,
            urgency=body.deadline.urgency,
            hubspot_contact_id=contact_id,
            hubspot_deal_id=deal_id,
            hubspot_task_id=task_id,
            hubspot_note_id=note_id,
            status="synced",
        )
        return ApproveResponse(
            status="synced",
            hubspot_contact_id=contact_id,
            hubspot_deal_id=deal_id,
            hubspot_task_id=task_id,
            hubspot_note_id=note_id,
            audit_id=audit_id or "unavailable",
        )
    except HTTPException:
        raise
    except HubSpotError as exc:
        log_event(
            review_id,
            "failed",
            reviewer=body.reviewer,
            error_code=f"{exc.operation}:{exc.status_code}",
        )
        logger.warning(
            "approve-and-sync crm failed operation=%s status=%s",
            exc.operation,
            exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CRM sync failed ({exc.operation})",
        ) from None
    except Exception:
        logger.exception("approve-and-sync failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from None
