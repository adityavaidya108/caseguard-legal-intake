from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    doc_type: Literal[
        "EOIR_HEARING_NOTICE",
        "I797C_NOTICE",
        "INTAKE_SHEET",
        "OTHER",
    ] = Field(
        description=(
            "Document type. Use EOIR_HEARING_NOTICE, I797C_NOTICE, INTAKE_SHEET, "
            "or OTHER based on the redacted text."
        )
    )
    matter_type: str = Field(
        description=(
            "Immigration matter type inferred from the notice, e.g. "
            "removal_proceedings, asylum, adjustment_of_status, family_petition."
        )
    )
    receipt_number: str | None = Field(
        default=None,
        description=(
            "USCIS receipt number when present (e.g. IOE0999123401). "
            "Null for EOIR hearing notices without a receipt number."
        ),
    )
    hearing_date: date | None = Field(
        default=None,
        description=(
            "Scheduled hearing date (YYYY-MM-DD). For rescheduled notices, "
            "this MUST be the NEW hearing date, not the previous one."
        ),
    )
    hearing_time: str | None = Field(
        default=None,
        description="Hearing time as written, e.g. '09:00 A.M.'. Null if none.",
    )
    hearing_type: Literal["MASTER", "INDIVIDUAL", "BOND", "OTHER"] | None = Field(
        default=None,
        description=(
            "Hearing type when stated: MASTER, INDIVIDUAL, BOND, or OTHER. "
            "Null if not indicated."
        ),
    )
    previous_hearing_date: date | None = Field(
        default=None,
        description=(
            "Prior hearing date when the notice resets/reschedules a hearing. "
            "Null if this is not a reschedule."
        ),
    )
    filing_deadline: date | None = Field(
        default=None,
        description=(
            "Evidence or filing deadline stated on the notice (YYYY-MM-DD). "
            "Null if none is given."
        ),
    )
    is_detained: bool = Field(
        description="True if the respondent is detained or the notice is a detained docket."
    )
    missing_docs: list[str] = Field(
        default_factory=list,
        description=(
            "Documents or items the notice says are missing or still needed. "
            "Empty list if none are mentioned."
        ),
    )
    draft_client_email: str = Field(
        description=(
            "Short draft email to the client summarizing the notice. "
            "Keep placeholder tokens like [CLIENT_NAME_1] exactly as they appear. "
            "Never invent dates or facts not in the text."
        )
    )


class DeadlineResult(BaseModel):
    task_due_date: date | None
    urgency: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    flags: list[str] = Field(default_factory=list)


class ExtractResponse(BaseModel):
    review_id: str
    filename: str
    raw_text: str
    redacted_text: str
    redaction_counts: dict[str, int]
    extraction: ExtractionResult
    deadline: DeadlineResult


class ApproveRequest(BaseModel):
    review_id: uuid.UUID
    reviewer: str = Field(min_length=1, max_length=100)
    extraction: ExtractionResult
    deadline: DeadlineResult


class ApproveResponse(BaseModel):
    status: str
    hubspot_contact_id: str
    hubspot_deal_id: str
    hubspot_task_id: str
    hubspot_note_id: str
    audit_id: str
