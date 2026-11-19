from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.pdf_reader import read_pdf
from backend.app.redactor import redact

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "sample_docs"

TIER1_CASES = [
    {
        "path": SAMPLE_ROOT
        / "01_ramirez"
        / "EOIR_01_master_calendar_hearing.pdf",
        "names": ["RAMIREZ, CARLOS ANDRES", "Carlos Andres Ramirez"],
        "a_numbers": ["A099-999-101"],
        "addresses": ["218 ELMORA AVE"],
        "must_remain": [
            "Jan 21, 2027",
            "MARGARET L. DOYLE",
            "1 FEDERAL SQUARE",
        ],
    },
    {
        "path": SAMPLE_ROOT
        / "02_okafor"
        / "EOIR_04_rescheduled_hearing_notice.pdf",
        "names": ["OKAFOR, CHIDINMA GRACE", "Chidinma Grace Okafor"],
        "a_numbers": ["A099-999-202"],
        "addresses": [],
        "must_remain": [
            "Feb 17, 2027",
            "MARGARET L. DOYLE",
            "1 FEDERAL SQUARE",
            "DELGADO & MEHTA",
            "1180 RAYMOND BLVD",
        ],
    },
    {
        "path": SAMPLE_ROOT
        / "04_hassan"
        / "EOIR_03_detained_master_hearing.pdf",
        "names": ["HASSAN, YUSUF ABDI", "Yusuf Abdi Hassan"],
        "a_numbers": ["A099-999-404"],
        "addresses": [],
        "must_remain": [
            "Nov 30, 2026",
            "ANTHONY J. PRESCOTT",
            "625 NORTH AVE EAST",
            "DETAINED",
        ],
    },
]


def _load(path: Path) -> str:
    return read_pdf(path.read_bytes(), path.name).text


@pytest.mark.parametrize("case", TIER1_CASES, ids=lambda c: c["path"].stem)
def test_tier1_eoir_redaction(case: dict) -> None:
    raw = _load(case["path"])
    result = redact(raw)

    lowered = result.redacted_text.lower()
    for name in case["names"]:
        assert name.lower() not in lowered

    for a_number in case["a_numbers"]:
        assert a_number not in result.redacted_text

    for address in case["addresses"]:
        assert address not in result.redacted_text

    for snippet in case["must_remain"]:
        assert snippet in result.redacted_text

    for token, original in result.vault.items():
        assert token.startswith("[") and token.endswith("]")
        assert original
        assert token in result.redacted_text
        assert result.vault[token] == original


def test_i797c_receipt_keeps_receipt_and_notice_dates() -> None:
    path = SAMPLE_ROOT / "01_ramirez" / "I-797C_01_I-130_receipt.pdf"
    result = redact(_load(path))

    assert "IOE0999123401" in result.redacted_text
    assert "10/02/2026" in result.redacted_text
    assert "10/09/2026" in result.redacted_text
    assert "03/14/1988" not in result.redacted_text
    assert "09/02/1990" not in result.redacted_text

