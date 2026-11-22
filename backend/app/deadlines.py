from __future__ import annotations

from datetime import date, timedelta

from backend.app.schemas import DeadlineResult, ExtractionResult

_PAST_FLAG = "14-day mark already passed"


def compute(extraction: ExtractionResult, today: date) -> DeadlineResult:
    """Compute task due date and urgency from extracted dates (not the LLM)."""
    hearing = extraction.hearing_date
    filing = extraction.filing_deadline

    if hearing is None and filing is None:
        return DeadlineResult(task_due_date=None, urgency="LOW", flags=[])

    candidates: list[date] = []
    hearing_minus_14: date | None = None
    if hearing is not None:
        hearing_minus_14 = hearing - timedelta(days=14)
        candidates.append(hearing_minus_14)
    if filing is not None:
        candidates.append(filing)

    due = min(candidates)

    if due < today:
        return DeadlineResult(
            task_due_date=today,
            urgency="CRITICAL",
            flags=[_PAST_FLAG],
        )

    if extraction.is_detained:
        urgency: str = "CRITICAL"
    elif hearing is not None and (hearing - today).days <= 30:
        urgency = "HIGH"
    elif (
        filing is not None
        and hearing_minus_14 is not None
        and filing < hearing_minus_14
    ):
        # Filing deadline drove the due date ahead of the default 14-day mark.
        urgency = "HIGH"
    elif hearing is None and filing is not None:
        urgency = "HIGH"
    else:
        urgency = "MEDIUM"

    return DeadlineResult(task_due_date=due, urgency=urgency, flags=[])
