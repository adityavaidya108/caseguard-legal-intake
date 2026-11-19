# Project Context: Privacy-First Immigration Intake & Court Notice-to-CRM Pipeline

## Goal
An end-to-end tool for an immigration law firm. It takes a USCIS I-797C Receipt Notice or an EOIR Court Hearing Notice (PDF), and optionally a firm intake sheet. It strips client PII locally **before** the LLM sees anything, puts a paralegal approval step in front of any write, then syncs Contact + Case (Deal) + Deadline Task + Note into HubSpot CRM and writes a PII-free audit log to Supabase.

## Stack
- Python 3.11+, Poetry, full type hints
- FastAPI (backend), Streamlit (UI, talks to backend over HTTP only)
- pdfplumber (PDF text extraction, in memory)
- Regex-first PII redaction
- **Claude (Anthropic API)** in `llm_claude.py`. It uses the commercial API, which does not train on inputs or outputs by default. Structured JSON comes from a forced tool call whose input schema is generated from the Pydantic model, then validated by Pydantic. `.env`: `LLM_PROVIDER=claude`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- HubSpot Private App API (scopes: contacts, deals, tasks only) in `hubspot.py`
- Supabase PostgreSQL (audit log)
- No n8n: FastAPI calls HubSpot directly through the CRM adapter (fewer hops, PII never leaves our service except to HubSpot)

## Pipeline
1. **Upload** (Streamlit) → `POST /extract` with one PDF + `X-API-Key` header
2. **Gateway** (FastAPI): validate (magic bytes `%PDF`, ≤10 MB, page cap) → pdfplumber text in memory → strip "SPECIMEN" lines → redact PII to tokens → store token→value vault in memory under a `review_id` with a TTL of about 30 minutes
3. **Claude**: receives ONLY redacted text and returns JSON:
   `doc_type, matter_type, receipt_number, hearing_date, hearing_type, previous_hearing_date, filing_deadline, is_detained, missing_docs[], draft_client_email`
4. **Deadlines** (code): compute task due date and urgency from the extracted dates (see Deadline Logic)
5. **Review** (Streamlit): paralegal sees raw vs redacted text, the extracted fields (editable), the due date + urgency (with a CRITICAL flag if one applies), the draft email and a count of hidden items → clicks **Approve & Sync**
6. **Sync**: `POST /approve-and-sync {review_id, reviewer, extraction, deadline}` (edited by the paralegal) → re-attach real values from the vault (in memory) → HubSpot upsert Contact, upsert Deal, create Task, add Note → Supabase audit row → delete the vault entry

## Scope (finish each tier fully before starting the next)
**Tier 1 — must work perfectly (this is the demo)**
- One PDF per upload; EOIR hearing notices
- Redaction: A-Number, SSN, DOB, passport, I-94, phone, email, address; names taken ONLY from known fields
- Claude extraction + Pydantic validation
- Deadline logic in code
- Review screen + Approve
- HubSpot: Contact, Deal, Task, Note
- Supabase audit row
- Test set: EOIR_01 (Ramirez, normal), EOIR_04 (Okafor, reschedule), EOIR_03 (Hassan, detained + past date)

**Tier 2 — only after Tier 1 works end to end**
- I-797C notices (same pipeline, `doc_type` branch)
- Intake sheets (adds SSN/passport redaction in the demo)
- Multiple docs per client update the same HubSpot Contact/Deal (match on A-Number, then email)
- Audit Log tab in the UI
- EOIR_02 (Nguyen, earlier filing deadline)

**Tier 3 — README "Extensibility" section only, do NOT build**
- OpenAI or other LLM adapter (Claude is the only implementation in Tier 1)
- Clio / Docketwise / Lawmatics CRM adapters
- Presidio / NER name detection
- HMAC inbound webhooks, auto-sending email, multi-user auth, deployment

Rule: if a feature isn't visible in the 3.5-minute video and isn't a security point, it's Tier 3.

## Security Rules (NON-NEGOTIABLE)
- Raw PDFs and real PII are never written to disk, the DB, logs or exception traces.
- The LLM only ever receives redacted text.
- Nothing is written to HubSpot without an explicit approval call.
- All secrets come from `.env` via pydantic-settings; `.env` is gitignored and `.env.example` is committed.
- The API key is checked on every endpoint (constant-time compare). `security.py` also includes HMAC-SHA256 sign/verify helpers (`X-Signature-256`) for future inbound webhooks.
- Audit rows store only: review_id, doc_type, redaction counts by type, reviewer, timestamps, HubSpot object IDs, status. No names, A-Numbers, SSNs, DOBs, emails or phones.
- Logging uses a filter that scrubs PII patterns as a safety net.
- Audit events: `extracted` (on /extract), `approved` (start of /approve-and-sync, records the reviewer), then `synced` or `failed`.
- `raw_text` is returned to the Streamlit UI only so the paralegal can compare; it is never logged or stored. Tier 1 runs locally (UI and API on the same machine).

## PII to Redact (tokens are numbered per review: `[A_NUMBER_1]`, `[A_NUMBER_2]`...)
- **A-Number** in every format: `A099-999-101`, `A-099-999-101`, `A 099 999 303`, `A#099999404`, `A099999404`, plus a bare `099-999-101` that follows "Case No.:/FILE A"
- **SSN**: `000-00-1234`, `666-01-2345`
- **Passport**: `X99887766`, `A09912345`, `C9912345`, `P99000111` (when near "Passport")
- **I-94 number** (11 digits near "I-94")
- **DOB**: dates near "Date of Birth"/"DOB"
- **Names**: taken from known fields (Petitioner, Beneficiary, Applicant, In the Matter of, Client Name, To:), then every occurrence of those names anywhere in the text is replaced (including "LAST, FIRST" and "First Last" order)
- **Email, phone** (all formats: `(973) 555-0142`, `201-555-0177`, `862.555.0123`), **client street address**
- Do NOT redact: receipt numbers (e.g. `IOE0999123401`), hearing dates, court address, judge name, law firm name, form types. The LLM needs these.

## Deadline Logic (in code, NOT left to the LLM)
- Default task due date = hearing_date − 14 days
- If the filing_deadline is earlier than that, use the filing_deadline
- If the computed due date is already past, due = today, urgency = CRITICAL, and the review screen shows a flag
- If the notice is a reschedule, use the NEW date (`previous_hearing_date` only goes in the Note)
- Detained → urgency CRITICAL
- Otherwise: hearing ≤ 30 days → HIGH, else MEDIUM
- No hearing date and no filing deadline → LOW (Tier 2 receipt notices)
- HubSpot task priority: CRITICAL/HIGH → HIGH, MEDIUM → MEDIUM, LOW → LOW

## Folder Structure (Tier 1 — flat on purpose)
```
caseguard-legal-intake/
├── pyproject.toml  .env.example  .gitignore  README.md  PROJECT_CONTEXT.md  CURSOR_PLAN.md
├── sample_docs/{01_ramirez,02_okafor,03_nguyen,04_hassan}/
├── backend/app/
│   ├── main.py        # FastAPI app + routes (/health, /extract, /approve-and-sync)
│   ├── config.py      # settings from .env
│   ├── security.py    # API key check (+ HMAC helpers)
│   ├── schemas.py     # all Pydantic models
│   ├── pdf_reader.py  # validate PDF -> text
│   ├── redactor.py    # text -> redacted text + vault map
│   ├── vault.py       # review_id -> vault, in memory, TTL
│   ├── llm_claude.py  # redacted text -> ExtractionResult
│   ├── deadlines.py   # due date + urgency
│   ├── hubspot.py     # contact, deal, task, note
│   └── audit.py       # Supabase insert
├── ui/app.py          # Streamlit: upload -> review -> approve
├── db/audit_table.sql
└── tests/{test_redactor.py, test_deadlines.py}
```
No adapter base classes in Tier 1. Keep hubspot.py and llm_claude.py as clean function sets so they can become adapters later.

## Sample Docs (synthetic) and Expected Outcomes
| Client | Files | Expected result |
|---|---|---|
| 01 Ramirez | EOIR_01 (master 2027-01-21) [T1]; I-797C_01, Intake_01 [T2] | Task due 2027-01-07, MEDIUM; missing_docs may be empty in Tier 1 (marriage evidence comes from the Tier 2 intake sheet) |
| 02 Okafor | EOIR_04 (reset 2026-12-15 → 2027-02-17) [T1]; I-797C_02, Intake_02 [T2] | Use NEW date, task 2027-02-03, MEDIUM; missing I-693 |
| 03 Nguyen | EOIR_02 (individual 2027-03-09) [T2]; I-797C_03, Intake_03 [T2] | Filing deadline 2027-02-22 is earlier than the 14-day mark, so use it; EAD task 2027-01-01; HIGH |
| 04 Hassan | EOIR_03 (detained master 2026-11-30) [T1]; I-797C_04, Intake_04 [T2] | Past 14-day mark → due today, CRITICAL; email to spouse Amina; reschedule biometrics |

## Build Order (Tier 1)
Follow CURSOR_PLAN.md one step at a time.

## Coding Conventions
- Small, single-purpose modules; services hold no FastAPI imports (keeps them testable)
- Pydantic models for every request and response
- No `print`; use `logging` with the PII-scrubbing filter
- Write a pytest for every service against `sample_docs/`
- Build one step at a time; do not scaffold future steps or tiers early
