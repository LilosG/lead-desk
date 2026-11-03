-- One server-side definition of "where is this prospect?". The Outreach page,
-- its counts and its filters all read this, so they can't disagree.

begin;

alter table outreach_queue
    add column if not exists contacted_at timestamptz,
    add column if not exists gmail_draft_left_at timestamptz;

-- Items already marked contacted: their last update is the best date we have.
update outreach_queue
set contacted_at = updated_at
where status in ('contacted', 'replied') and contacted_at is null;

create index if not exists idx_outreach_queue_gmail_open
    on outreach_queue (gmail_draft_created_at)
    where gmail_draft_id is not null and status in ('draft_ready', 'approved');

create or replace view v_outreach_stage as
select
    q.id,
    q.place_id,
    case
        when q.status in ('archived', 'suppressed') then 'closed'
        when q.status = 'replied' then 'replied'
        when q.status = 'contacted' then 'contacted'
        when q.channel <> 'email' then 'call'
        when q.gmail_draft_id is not null then 'in_gmail'
        when q.status = 'no_outreach_finding' or q.verification_status = 'failed' then 'attention'
        else 'review'
    end as stage
from outreach_queue q;

commit;
