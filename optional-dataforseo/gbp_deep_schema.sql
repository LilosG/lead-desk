-- Optional deep-enrichment table. Only needed if you sign up for DataForSEO.
-- Run in the Supabase SQL Editor.
create table if not exists gbp_deep (
  place_id                  text primary key references businesses(place_id) on delete cascade,
  fetched_at                timestamptz not null default now(),
  services_count            int,
  services_have_descriptions boolean,
  description_present       boolean,
  description_length        int,
  is_claimed                boolean,
  category                  text,
  total_photos              int,
  reviews_sampled           int,
  reviews_with_owner_reply  int,
  owner_reply_rate          numeric(4,3),
  newest_review_iso         text,
  raw_payload               jsonb
);

-- Which leads have deep data, and what it says. Joins onto the main list.
create or replace view v_leads_enriched as
select l.*, d.services_count, d.description_present,
       d.reviews_with_owner_reply, d.reviews_sampled, d.owner_reply_rate,
       d.is_claimed, d.fetched_at as enriched_at
from v_leads l
join gbp_deep d on d.place_id = l.place_id
order by l.score desc;
