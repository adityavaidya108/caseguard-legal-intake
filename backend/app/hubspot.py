# HubSpot Private App / service key scopes used:
# - crm.objects.contacts.read
# - crm.objects.contacts.write
# - crm.objects.deals.read
# - crm.objects.deals.write
# Tasks and notes use the CRM objects APIs under the same app; grant task/note
# object access in the Private App if HubSpot requires separate scopes.

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

A_NUMBER_PROPERTY = "anumber"
_BASE_URL = "https://api.hubapi.com"
_TIMEOUT_SECONDS = 20.0
_NY = ZoneInfo("America/New_York")


class HubSpotError(Exception):
    """HubSpot API failure. Holds status_code and operation name only."""

    def __init__(self, status_code: int, operation: str) -> None:
        self.status_code = status_code
        self.operation = operation
        super().__init__(f"HubSpot {operation} failed ({status_code})")


def _client() -> httpx.Client:
    token = get_settings().hubspot_token.get_secret_value()
    return httpx.Client(
        base_url=_BASE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=_TIMEOUT_SECONDS,
    )


def _request(
    method: str,
    path: str,
    *,
    operation: str,
    json: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        with _client() as client:
            response = client.request(method, path, json=json)
    except httpx.HTTPError:
        logger.warning("hubspot transport error operation=%s", operation)
        raise HubSpotError(0, operation) from None

    if response.status_code >= 400:
        logger.warning(
            "hubspot error operation=%s status=%s",
            operation,
            response.status_code,
        )
        raise HubSpotError(response.status_code, operation)

    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _search_first(
    object_type: str,
    property_name: str,
    value: str,
    *,
    operation: str,
) -> str | None:
    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": property_name,
                        "operator": "EQ",
                        "value": value,
                    }
                ]
            }
        ],
        "limit": 1,
    }
    data = _request(
        "POST",
        f"/crm/v3/objects/{object_type}/search",
        operation=operation,
        json=payload,
    )
    results = (data or {}).get("results") or []
    if not results:
        return None
    return str(results[0]["id"])


def _associate_default(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    *,
    operation: str,
) -> None:
    _request(
        "PUT",
        f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}",
        operation=operation,
    )


def upsert_contact(
    first_name: str,
    last_name: str,
    a_number: str,
    email: str | None = None,
    phone: str | None = None,
) -> str:
    properties: dict[str, str] = {
        "firstname": first_name,
        "lastname": last_name,
        A_NUMBER_PROPERTY: a_number,
    }
    if email:
        properties["email"] = email
    if phone:
        properties["phone"] = phone

    existing_id = _search_first(
        "contacts",
        A_NUMBER_PROPERTY,
        a_number,
        operation="search_contact",
    )
    if existing_id:
        _request(
            "PATCH",
            f"/crm/v3/objects/contacts/{existing_id}",
            operation="update_contact",
            json={"properties": properties},
        )
        return existing_id

    created = _request(
        "POST",
        "/crm/v3/objects/contacts",
        operation="create_contact",
        json={"properties": properties},
    )
    return str((created or {})["id"])


def upsert_deal(name: str, contact_id: str) -> str:
    existing_id = _search_first(
        "deals",
        "dealname",
        name,
        operation="search_deal",
    )
    if existing_id is None:
        created = _request(
            "POST",
            "/crm/v3/objects/deals",
            operation="create_deal",
            json={
                "properties": {
                    "dealname": name,
                    "pipeline": "default",
                    "dealstage": "appointmentscheduled",
                }
            },
        )
        deal_id = str((created or {})["id"])
    else:
        deal_id = existing_id

    _associate_default(
        "deals",
        deal_id,
        "contacts",
        contact_id,
        operation="associate_deal_contact",
    )
    return deal_id


def create_task(
    subject: str,
    body: str,
    due_date: date,
    priority: str,
    contact_id: str,
    deal_id: str,
) -> str:
    due_at = datetime.combine(due_date, time(9, 0), tzinfo=_NY).isoformat()
    created = _request(
        "POST",
        "/crm/v3/objects/tasks",
        operation="create_task",
        json={
            "properties": {
                "hs_task_subject": subject,
                "hs_task_body": body,
                "hs_task_status": "NOT_STARTED",
                "hs_task_priority": priority,
                "hs_timestamp": due_at,
            }
        },
    )
    task_id = str((created or {})["id"])
    _associate_default(
        "tasks",
        task_id,
        "contacts",
        contact_id,
        operation="associate_task_contact",
    )
    _associate_default(
        "tasks",
        task_id,
        "deals",
        deal_id,
        operation="associate_task_deal",
    )
    return task_id


def create_note(body: str, contact_id: str, deal_id: str) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    created = _request(
        "POST",
        "/crm/v3/objects/notes",
        operation="create_note",
        json={
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": now_iso,
            }
        },
    )
    note_id = str((created or {})["id"])
    _associate_default(
        "notes",
        note_id,
        "contacts",
        contact_id,
        operation="associate_note_contact",
    )
    _associate_default(
        "notes",
        note_id,
        "deals",
        deal_id,
        operation="associate_note_deal",
    )
    return note_id
