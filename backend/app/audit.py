from __future__ import annotations

import logging
from typing import Any, Literal

from supabase import Client, create_client

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

EventName = Literal["extracted", "approved", "synced", "failed"]

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(
            settings.supabase_url,
            settings.supabase_key.get_secret_value(),
        )
    return _client


def log_event(
    review_id: str,
    event: EventName,
    *,
    doc_type: str | None = None,
    redaction_counts: dict[str, int] | None = None,
    urgency: str | None = None,
    reviewer: str | None = None,
    hubspot_contact_id: str | None = None,
    hubspot_deal_id: str | None = None,
    hubspot_task_id: str | None = None,
    hubspot_note_id: str | None = None,
    status: str | None = None,
    error_code: str | None = None,
) -> str | None:
    """Insert one append-only audit row. Returns id, or None if insert fails."""
    row: dict[str, Any] = {
        "review_id": review_id,
        "event": event,
        "doc_type": doc_type,
        "redaction_counts": redaction_counts,
        "urgency": urgency,
        "reviewer": reviewer,
        "hubspot_contact_id": hubspot_contact_id,
        "hubspot_deal_id": hubspot_deal_id,
        "hubspot_task_id": hubspot_task_id,
        "hubspot_note_id": hubspot_note_id,
        "status": status,
        "error_code": error_code,
    }
    try:
        result = _get_client().table("automation_audit_logs").insert(row).execute()
        data = result.data or []
        if not data:
            logger.warning("audit insert returned no row event=%s", event)
            return None
        return str(data[0]["id"])
    except Exception:
        logger.warning("audit insert failed event=%s", event)
        return None
