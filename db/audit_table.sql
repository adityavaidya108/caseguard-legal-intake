create table public.automation_audit_logs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  review_id uuid not null,
  event text not null check (event in ('extracted','approved','synced','failed')),
  doc_type text,
  redaction_counts jsonb,
  urgency text,
  reviewer text,
  hubspot_contact_id text,
  hubspot_deal_id text,
  hubspot_task_id text,
  hubspot_note_id text,
  status text,
  error_code text
);

alter table public.automation_audit_logs enable row level security;

-- Append-only: nobody can edit or delete audit rows through the API
revoke update, delete on public.automation_audit_logs from anon, authenticated, service_role;
revoke all on public.automation_audit_logs from anon, authenticated;