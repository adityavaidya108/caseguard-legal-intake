# CaseGuard — Privacy-First Immigration Notice Intake

CaseGuard reads immigration court notices, hides client details on our own server before AI sees anything, uses Claude to extract hearing dates and draft a client update, calculates deadlines and flags urgent cases in code, and a staff member reviews and approves before anything is saved to the CRM. Nothing is ever sent to the client automatically.

## Demo

Loom: [Watch the demo](https://www.loom.com/share/188e467efcfa4f9abfa8efcc2159f0ea)

## How it works

```
Upload PDF
    -> Validate
    -> Hide client details (vault in memory)
    -> Claude (hidden text only)
    -> Deadline rules (code)
    -> Paralegal review & edit
    -> Approve
    -> Put real details back (in memory)
    -> HubSpot (Contact, Deal, Task, Note)
    -> Audit log (Supabase)
```

## Security & Confidentiality

1. **Claude never sees real client details.** Names, A-Numbers, and addresses are replaced with tokens like `[CLIENT_NAME_1]`.
2. **Real details live only in memory.** They expire after 30 minutes, are deleted after sync, and are never written to disk or logs.
3. **Human approval gate.** Nothing reaches the CRM until a staff member reviews and approves. Draft emails are saved as notes, never sent.
4. **Locked doors.** An API key is required on every request (constant-time check). Secrets stay in `.env`. The HubSpot service key is limited to contacts and deals.
5. **Clean records.** An append-only Supabase audit log (RLS on; update/delete revoked) stores only event, counts, reviewer, urgency, and CRM IDs — no client data. A log filter masks personal data, including in error traces.

## Deadline rules (in code, not AI)

- Default due date = hearing date minus 14 days
- An earlier filing deadline wins
- Already past → due today + **CRITICAL**
- Detained → **CRITICAL**
- Rescheduled notices use the **new** hearing date
- HubSpot task priority: CRITICAL / HIGH → High

## Tested scenarios

| Client | Scenario | Result |
|--------|----------|--------|
| Ramirez | Normal master hearing | MEDIUM; due 14 days before the hearing |
| Okafor | Rescheduled hearing | Uses the **new** date for the task |
| Hassan | Detained + 14-day mark already passed | CRITICAL; due today |

## Tech stack

Python · FastAPI · Streamlit · pdfplumber · Claude API (Anthropic) · HubSpot CRM API · Supabase (Postgres) · pytest

## What's next

- USCIS I-797C notices and client intake sheets (samples already in `sample_docs/`)
- CRM adapters for Clio, Docketwise, or Lawmatics (HubSpot is isolated in one module)
- NER-based name detection
- Multi-user login
- Deployment

## Run locally

```bash
poetry install
cp .env.example .env   # then fill in keys
```

```bash
# single worker: the vault is in memory
poetry run uvicorn backend.app.main:app --port 8010
poetry run streamlit run ui/app.py
poetry run pytest -v
```

- **Supabase:** run [`db/audit_table.sql`](db/audit_table.sql)
- **HubSpot:** create a contact property with internal name `anumber`

## Demo data

All documents in `sample_docs/` are synthetic. Names, numbers, and addresses are fictitious.
