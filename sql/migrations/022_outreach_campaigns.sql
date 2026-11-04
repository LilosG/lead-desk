-- Outreach campaigns: the same business can be in more than one pitch, each
-- with its own stage and draft. Existing work moves to SEO + Websites.

begin;

create table if not exists campaigns (
    key         text primary key,
    name        text not null,
    description text not null,
    sort_order  integer not null default 0,
    active      boolean not null default true,
    created_at  timestamptz not null default now()
);

insert into campaigns (key, name, description, sort_order) values
    ('seo_websites', 'SEO + Websites', 'Audit-led outreach for local SEO and website work', 1),
    ('ev_permits', 'EV Permits', 'Permit paperwork automation for electricians doing EV installs', 2)
on conflict (key) do nothing;

alter table outreach_queue
    add column if not exists campaign_key text not null default 'seo_websites'
        references campaigns (key);

alter table outreach_queue
    drop constraint if exists outreach_queue_place_id_channel_key;

alter table outreach_queue
    add constraint outreach_queue_place_channel_campaign_key
        unique (place_id, channel, campaign_key);

create index if not exists idx_outreach_queue_campaign_status
    on outreach_queue (campaign_key, status);

commit;
