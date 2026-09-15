create table if not exists gmail_draft_operations (
    id uuid primary key default gen_random_uuid(),
    queue_id uuid not null references outreach_queue(id) on delete cascade,
    queue_version integer not null,
    message_id_header text not null unique,
    state text not null default 'pending',
    gmail_draft_id text,
    gmail_message_id text,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint gmail_draft_operations_state_valid
        check (state in ('pending', 'created', 'failed')),
    constraint gmail_draft_operations_queue_version_unique
        unique (queue_id, queue_version)
);

create unique index if not exists idx_gmail_draft_operations_one_pending_per_queue
    on gmail_draft_operations (queue_id)
    where state = 'pending';

create index if not exists idx_gmail_draft_operations_state
    on gmail_draft_operations (state, updated_at);
