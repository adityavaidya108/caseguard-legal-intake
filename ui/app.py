from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Immigration Notice Intake", layout="wide")
st.title("Immigration Notice Intake")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("GATEWAY_API_KEY", "")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _hidden_count(counts: dict[str, int] | None) -> int:
    if not counts:
        return 0
    return sum(counts.values())


def _client() -> httpx.Client:
    if not API_KEY:
        raise RuntimeError("GATEWAY_API_KEY is not set in the environment.")
    return httpx.Client(
        base_url=BACKEND_URL,
        headers={"X-API-Key": API_KEY},
        timeout=120.0,
    )


def _call_extract(pdf_bytes: bytes, filename: str) -> dict[str, Any]:
    with _client() as client:
        response = client.post(
            "/extract",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
    if response.status_code == 401:
        raise RuntimeError("Unauthorized — check GATEWAY_API_KEY.")
    if response.status_code >= 400:
        detail = (
            response.json().get("detail", response.text)
            if response.headers.get("content-type", "").startswith("application/json")
            else response.text
        )
        raise RuntimeError(f"Extract failed ({response.status_code}): {detail}")
    return response.json()


def _call_approve(payload: dict[str, Any]) -> dict[str, Any]:
    with _client() as client:
        response = client.post("/approve-and-sync", json=payload)
    if response.status_code == 401:
        raise RuntimeError("Unauthorized — check GATEWAY_API_KEY.")
    if response.status_code >= 400:
        detail = (
            response.json().get("detail", response.text)
            if response.headers.get("content-type", "").startswith("application/json")
            else response.text
        )
        raise RuntimeError(str(detail))
    return response.json()


if "extract_result" not in st.session_state:
    st.session_state.extract_result = None
if "reviewer" not in st.session_state:
    st.session_state.reviewer = ""
if "sync_result" not in st.session_state:
    st.session_state.sync_result = None

uploaded = st.file_uploader("Upload one PDF notice", type=["pdf"])

if uploaded is not None and st.button("Extract", type="primary"):
    with st.spinner("Reading and redacting notice…"):
        try:
            result = _call_extract(uploaded.getvalue(), uploaded.name)
            st.session_state.extract_result = result
            st.session_state.sync_result = None
        except Exception as exc:
            st.session_state.extract_result = None
            st.session_state.sync_result = None
            st.error(str(exc))

result = st.session_state.extract_result
if not result:
    st.info("Upload a PDF and click Extract to begin review.")
    st.stop()

extraction = result.get("extraction") or {}
deadline = result.get("deadline") or {}
urgency = deadline.get("urgency") or "MEDIUM"
flags = deadline.get("flags") or []
hidden = _hidden_count(result.get("redaction_counts"))

if urgency == "CRITICAL":
    flag_text = "; ".join(flags) if flags else "Immediate attention required."
    st.error(f"**CRITICAL** — {flag_text}")

st.caption(f"File: **{result.get('filename', '')}** · Review ID: `{result.get('review_id', '')}`")

left, right = st.columns(2)
with left:
    st.subheader("Original (stays on our server)")
    st.text_area(
        "raw_text",
        value=result.get("raw_text") or "",
        height=320,
        disabled=True,
        label_visibility="collapsed",
    )
with right:
    st.subheader("Sent to Claude (redacted)")
    st.markdown(f"**{hidden} items hidden**")
    st.text_area(
        "redacted_text",
        value=result.get("redacted_text") or "",
        height=320,
        disabled=True,
        label_visibility="collapsed",
    )

st.subheader("Review & edit")

matter_type = st.text_input("Matter type", value=extraction.get("matter_type") or "")

hearing_date_val = _parse_date(extraction.get("hearing_date"))
use_hearing = st.checkbox("Has hearing date", value=hearing_date_val is not None)
hearing_date = None
if use_hearing:
    hearing_date = st.date_input(
        "Hearing date",
        value=hearing_date_val or date.today(),
        format="YYYY-MM-DD",
    )

hearing_types = ["", "MASTER", "INDIVIDUAL", "BOND", "OTHER"]
current_hearing_type = extraction.get("hearing_type") or ""
hearing_type_index = (
    hearing_types.index(current_hearing_type)
    if current_hearing_type in hearing_types
    else 0
)
hearing_type = st.selectbox("Hearing type", hearing_types, index=hearing_type_index)

filing_deadline_val = _parse_date(extraction.get("filing_deadline"))
use_filing = st.checkbox(
    "Has filing deadline",
    value=filing_deadline_val is not None,
)
filing_deadline = None
if use_filing:
    filing_deadline = st.date_input(
        "Filing deadline",
        value=filing_deadline_val or date.today(),
        format="YYYY-MM-DD",
    )

is_detained = st.checkbox("Detained", value=bool(extraction.get("is_detained")))

missing_docs_text = st.text_area(
    "Missing docs (one per line)",
    value="\n".join(extraction.get("missing_docs") or []),
    height=100,
)

due_val = _parse_date(deadline.get("task_due_date"))
use_due = st.checkbox("Has task due date", value=due_val is not None)
task_due_date = None
if use_due:
    task_due_date = st.date_input(
        "Task due date",
        value=due_val or date.today(),
        format="YYYY-MM-DD",
    )

urgency_options = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
urgency_index = (
    urgency_options.index(urgency) if urgency in urgency_options else 1
)
urgency_edit = st.selectbox("Urgency", urgency_options, index=urgency_index)

draft_client_email = st.text_area(
    "Draft client email",
    value=extraction.get("draft_client_email") or "",
    height=220,
)

reviewer = st.text_input(
    "Reviewer name",
    value=st.session_state.reviewer,
    max_chars=100,
)
st.session_state.reviewer = reviewer

edited_extraction = {
    **extraction,
    "matter_type": matter_type,
    "hearing_date": hearing_date.isoformat() if hearing_date else None,
    "hearing_type": hearing_type or None,
    "filing_deadline": filing_deadline.isoformat() if filing_deadline else None,
    "is_detained": is_detained,
    "missing_docs": [
        line.strip() for line in missing_docs_text.splitlines() if line.strip()
    ],
    "draft_client_email": draft_client_email,
}
edited_deadline = {
    "task_due_date": task_due_date.isoformat() if task_due_date else None,
    "urgency": urgency_edit,
    "flags": flags,
}

if st.button("Approve & Sync to HubSpot", type="primary"):
    if not reviewer.strip():
        st.error("Enter a reviewer name before approving.")
    else:
        with st.spinner("Syncing to HubSpot…"):
            try:
                sync = _call_approve(
                    {
                        "review_id": result["review_id"],
                        "reviewer": reviewer.strip(),
                        "extraction": edited_extraction,
                        "deadline": edited_deadline,
                    }
                )
                st.session_state.sync_result = sync
            except Exception as exc:
                st.session_state.sync_result = None
                st.error(str(exc))

sync_result = st.session_state.sync_result
if sync_result:
    st.success(
        "Synced to HubSpot.\n\n"
        f"- Contact: `{sync_result.get('hubspot_contact_id')}`\n"
        f"- Deal: `{sync_result.get('hubspot_deal_id')}`\n"
        f"- Task: `{sync_result.get('hubspot_task_id')}`\n"
        f"- Note: `{sync_result.get('hubspot_note_id')}`\n"
        f"- Audit: `{sync_result.get('audit_id')}`\n\n"
        "Draft email saved to HubSpot as a note. Nothing was sent to the client."
    )
