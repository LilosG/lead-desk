create table if not exists prospect_audit_reports (
  id                  uuid primary key default gen_random_uuid(),
  place_id            text not null references businesses(place_id) on delete cascade,
  report_version      integer not null default 1,
  status              text not null default 'generated',
  title               text not null,
  selected_signals    text[] not null default '{}'::text[],
  snapshot             jsonb not null,
  source_checked_at    timestamptz,
  created_at           timestamptz not null default now(),
  constraint prospect_audit_reports_status_valid
    check (status in ('generated','archived'))
);

create index if not exists idx_prospect_audit_reports_place
  on prospect_audit_reports(place_id, created_at desc);
