-- Migration 023 cleaned bad addresses off the lead, but items already queued
-- kept theirs. Unsent items take the lead's best real address, or wait for one.

begin;

update outreach_queue q
set to_address = (
        select we.emails_found[1]
        from website_enrichment we
        where we.place_id = q.place_id
    ),
    version = q.version + 1,
    updated_at = now()
where q.channel = 'email'
  and q.to_address is not null
  and q.to_address !~* '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
  and q.gmail_draft_id is null
  and q.contacted_at is null;

commit;
