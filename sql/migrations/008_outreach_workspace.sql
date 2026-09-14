create table if not exists outreach_queue (
  id                  uuid primary key default gen_random_uuid(),
  place_id            text not null references businesses(place_id) on delete cascade,
  channel             text not null,
  status              text not null default 'queued',
  to_address          text,
  subject             text,
  body                text,
  claim_signal        text,
  verification_status text not null default 'pending',
  verification_note   text,
  version             integer not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint outreach_queue_channel_valid
    check (channel in ('email','phone','form')),
  constraint outreach_queue_status_valid
    check (status in ('queued','researching','review_required','draft_ready','approved','contacted','replied','archived','suppressed')),
  constraint outreach_queue_verification_valid
    check (verification_status in ('pending','verified','failed','not_required')),
  unique (place_id, channel)
);

create index if not exists idx_outreach_queue_status
  on outreach_queue(status, updated_at desc);

create index if not exists idx_outreach_queue_place
  on outreach_queue(place_id);

create table if not exists outreach_queue_events (
  id          uuid primary key default gen_random_uuid(),
  queue_id    uuid not null references outreach_queue(id) on delete cascade,
  place_id    text not null references businesses(place_id) on delete cascade,
  event_type  text not null,
  changes     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists idx_outreach_queue_events_queue
  on outreach_queue_events(queue_id, created_at desc);

create index if not exists idx_outreach_queue_events_place
  on outreach_queue_events(place_id, created_at desc);
