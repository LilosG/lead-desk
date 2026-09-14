begin;

create table if not exists prospect_workflow (
    place_id text primary key references businesses(place_id) on delete cascade,
    status text not null default 'new',
    priority text not null default 'normal',
    owner text,
    next_action text,
    next_action_at timestamptz,
    notes text,
    version integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint prospect_workflow_status_valid check (
        status in (
            'new',
            'researching',
            'qualified',
            'outreach_ready',
            'contacted',
            'replied',
            'won',
            'lost',
            'disqualified'
        )
    ),
    constraint prospect_workflow_priority_valid check (
        priority in ('low', 'normal', 'high', 'urgent')
    ),
    constraint prospect_workflow_version_positive check (version > 0)
);

create index if not exists idx_prospect_workflow_status
    on prospect_workflow(status);

create index if not exists idx_prospect_workflow_priority
    on prospect_workflow(priority);

create index if not exists idx_prospect_workflow_next_action_at
    on prospect_workflow(next_action_at)
    where next_action_at is not null;

create table if not exists prospect_workflow_events (
    id uuid primary key default gen_random_uuid(),
    place_id text not null references businesses(place_id) on delete cascade,
    event_type text not null,
    changes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),

    constraint prospect_workflow_event_type_valid check (
        event_type in ('created', 'updated')
    )
);

create index if not exists idx_prospect_workflow_events_place_created
    on prospect_workflow_events(place_id, created_at desc);

commit;
