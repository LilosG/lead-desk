-- Which email angle each lead got, so reply rates can be compared, and the
-- follow-ups in each sequence. A follow-up is a Gmail draft in the same thread.

begin;

alter table outreach_queue
    add column if not exists angle text,
    add column if not exists gmail_thread_id text;

create table if not exists outreach_follow_ups (
    id                uuid primary key default gen_random_uuid(),
    queue_id          uuid not null references outreach_queue (id) on delete cascade,
    step              integer not null check (step in (2, 3)),
    subject           text not null,
    body              text not null,
    message_id_header text not null,
    gmail_draft_id    text,
    gmail_message_id  text,
    created_at        timestamptz not null default now(),
    sent_at           timestamptz,
    unique (queue_id, step)
);

create index if not exists idx_outreach_follow_ups_open
    on outreach_follow_ups (queue_id)
    where gmail_draft_id is not null and sent_at is null;

commit;
