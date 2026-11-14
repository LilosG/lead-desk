-- "Who does ChatGPT recommend?" lookups, cached per market (trade + city + state)
-- so one call covers every lead in that market. Each lead's email keeps the
-- exact evidence it was written from.

begin;

create table if not exists chatgpt_checks (
    id          uuid primary key default gen_random_uuid(),
    vertical    text not null,
    city        text not null,
    state       text not null default '',
    prompt      text not null,
    response    text not null,
    sources     jsonb not null default '[]'::jsonb,
    businesses  jsonb not null default '[]'::jsonb,
    model       text not null,
    checked_at  timestamptz not null default now()
);

create index if not exists idx_chatgpt_checks_market
    on chatgpt_checks (vertical, city, state, checked_at desc);

alter table outreach_queue
    add column if not exists chatgpt_evidence jsonb;

commit;
