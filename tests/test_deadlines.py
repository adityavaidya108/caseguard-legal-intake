from __future__ import annotations

from datetime import date

from backend.app.deadlines import compute
from backend.app.schemas import ExtractionResult

TODAY = date(2026, 11, 19)


def _extraction(**kwargs: object) -> ExtractionResult:
    defaults: dict[str, object] = {
        "doc_type": "EOIR_HEARING_NOTICE",
        "matter_type": "removal_proceedings",
        "is_detained": False,
        "missing_docs": [],
        "draft_client_email": "Hello [CLIENT_NAME_1]",
    }
    defaults.update(kwargs)
    return ExtractionResult.model_validate(defaults)


def test_ramirez_medium() -> None:
    result = compute(
        _extraction(hearing_date=date(2027, 1, 21), hearing_type="MASTER"),
        TODAY,
    )
    assert result.task_due_date == date(2027, 1, 7)
    assert result.urgency == "MEDIUM"
    assert result.flags == []


def test_okafor_reschedule_uses_new_date() -> None:
    result = compute(
        _extraction(
            hearing_date=date(2027, 2, 17),
            previous_hearing_date=date(2026, 12, 15),
            hearing_type="MASTER",
        ),
        TODAY,
    )
    assert result.task_due_date == date(2027, 2, 3)
    assert result.urgency == "MEDIUM"
    assert result.flags == []


def test_hassan_detained_past_14_day_mark() -> None:
    result = compute(
        _extraction(
            hearing_date=date(2026, 11, 30),
            hearing_type="MASTER",
            is_detained=True,
        ),
        TODAY,
    )
    assert result.task_due_date == TODAY
    assert result.urgency == "CRITICAL"
    assert "14-day mark already passed" in result.flags


def test_nguyen_filing_deadline_earlier_high() -> None:
    result = compute(
        _extraction(
            hearing_date=date(2027, 3, 9),
            filing_deadline=date(2027, 2, 22),
            hearing_type="INDIVIDUAL",
        ),
        TODAY,
    )
    assert result.task_due_date == date(2027, 2, 22)
    assert result.urgency == "HIGH"
    assert result.flags == []
