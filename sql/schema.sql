-- Lilos Growth — Lead Aggregator schema
-- Target: Supabase / Postgres. Apply via Supabase SQL editor.
-- Design notes:
--   * place_id is the natural key from Google. Everything upserts on it, so
--     re-running a sweep updates rather than duplicates.
--   * Raw API payloads are retained in jsonb so we can re-score historically
--     without re-paying for API calls. This is deliberate: scoring weights WILL
--     change after the first review pass, and re-scoring from cache must be free.
--   * Evidence is stored per-signal, not as a blob, so the outreach layer and the
--     free-GBP-audit PDF can both read structured findings.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Runs: every sweep is recorded so results are reproducible and attributable
-- ---------------------------------------------------------------------------
create table if not exists runs (
  id                uuid primary key default gen_random_uuid(),
  started_at        timestamptz not null default now(),
  finished_at       timestamptz,
  geo_label         text not null,             -- 'San Diego County'
  verticals         text[] not null,           -- ['electrician','plumber']
  grid_points       int,
  api_calls_search  int default 0,
  api_calls_details int default 0,
  api_calls_psi     int default 0,
  est_cost_usd      numeric(10,4) default 0,
  dry_run           boolean not null default false,
  notes             text,

  -- staged-run lifecycle / telemetry
  status                text not null default 'completed',
  stage                 text,
  businesses_discovered integer not null default 0,
  websites_crawled      integer not null default 0,
  psi_completed         integer not null default 0,
  discovery_finished_at timestamptz,
  crawl_finished_at     timestamptz,
  psi_finished_at       timestamptz,

  constraint runs_status_valid
    check (status in ('running', 'completed', 'failed', 'abandoned')),

  constraint runs_stage_valid
    check (
      stage is null or
      stage in ('discovery', 'crawl', 'psi', 'finalize', 'completed')
    ),

  constraint runs_businesses_discovered_nonnegative
    check (businesses_discovered >= 0),

  constraint runs_websites_crawled_nonnegative
    check (websites_crawled >= 0),

  constraint runs_psi_completed_nonnegative
    check (psi_completed >= 0)
);

-- ---------------------------------------------------------------------------
-- Businesses: one row per GBP, upserted on place_id
-- ---------------------------------------------------------------------------
create table if not exists businesses (
  place_id            text primary key,
  first_seen_run      uuid references runs(id),
  last_seen_run       uuid references runs(id),
  first_seen_at       timestamptz not null default now(),
  last_seen_at        timestamptz not null default now(),

  -- identity
  name                text,
  vertical            text,                    -- our search term bucket
  primary_type        text,                    -- google's primaryType
  types               text[],
  business_status     text,                    -- OPERATIONAL / CLOSED_TEMPORARILY / ...

  -- location
  formatted_address   text,
  street              text,
  city                text,
  state               text,
  postal_code         text,
  lat                 double precision,
  lng                 double precision,

  -- contact (from GBP)
  phone               text,
  website_url         text,
  google_maps_uri     text,

  -- GBP quality signals
  rating              numeric(2,1),
  review_count        int,
  last_review_days     integer,
  recent_reviews_90d   integer,
  has_hours           boolean,
  hours_json          jsonb,
  photo_count         int,

  raw_places_payload  jsonb,                   -- full API response, for re-scoring

  unique_key          text generated always as (place_id) stored
);

create index if not exists idx_businesses_vertical  on businesses(vertical);
create index if not exists idx_businesses_city      on businesses(city);
create index if not exists idx_businesses_website   on businesses(website_url);
create index if not exists idx_businesses_reviews   on businesses(review_count);

-- ---------------------------------------------------------------------------
-- Website enrichment: results of crawling the prospect's own site
-- ---------------------------------------------------------------------------
create table if not exists website_enrichment (
  place_id              text primary key references businesses(place_id) on delete cascade,
  checked_at            timestamptz not null default now(),

  -- reachability of the site itself
  resolved_url          text,
  http_status           int,
  is_reachable          boolean,
  has_ssl               boolean,
  redirects_to          text,

  -- SEO fundamentals
  title                 text,
  title_length          int,
  meta_description      text,
  meta_desc_length      int,
  h1_text               text,
  h1_count              int,
  word_count            int,
  page_count_estimate   int,

  -- local SEO specifics (the stuff Lilos sells)
  has_localbusiness_schema boolean,
  schema_types          text[],
  nap_phone_on_site     text,
  nap_address_on_site   text,
  nap_matches_gbp       boolean,
  has_service_pages     boolean,
  has_city_pages        boolean,
  has_gbp_link          boolean,

  -- conversion surface
  has_contact_form      boolean,
  contact_page_url      text,
  emails_found          text[],
  phones_found          text[],
  social_profiles       jsonb,

  -- tech stack
  cms_detected          text,                  -- wordpress / wix / squarespace / godaddy / custom
  is_template_builder   boolean,               -- wix/squarespace/godaddy = easy displacement

  -- performance (PageSpeed Insights)
  psi_performance       int,
  psi_seo               int,
  psi_accessibility     int,
  psi_best_practices    int,
  psi_lcp_ms            int,
  psi_cls               numeric(5,3),
  psi_mobile_friendly   boolean,

  crawl_error           text,
  raw_psi_payload       jsonb
);

-- ---------------------------------------------------------------------------
-- Scores: one row per business per scoring-model version.
-- Keeping model_version means we can re-score without destroying history and
-- compare "did the new weights actually rank better?"
-- ---------------------------------------------------------------------------
create table if not exists scores (
  id                uuid primary key default gen_random_uuid(),
  place_id          text not null references businesses(place_id) on delete cascade,
  run_id            uuid references runs(id),
  model_version     text not null,
  scored_at         timestamptz not null default now(),

  total_score       int not null,              -- 0-100, higher = better prospect
  gbp_gap_score     int,
  website_gap_score int,
  reachability_score int,

  tier              text,                      -- A / B / C / D
  headline_gap      text,                      -- the single most pitchable finding
  unique (place_id, model_version, run_id)
);

create index if not exists idx_scores_total on scores(total_score desc);
create index if not exists idx_scores_tier  on scores(tier);

-- ---------------------------------------------------------------------------
-- Evidence: structured per-signal findings behind every score.
-- This is what powers both the outreach copy and the free GBP audit PDF.
-- ---------------------------------------------------------------------------
create table if not exists score_evidence (
  id            uuid primary key default gen_random_uuid(),
  score_id      uuid not null references scores(id) on delete cascade,
  place_id      text not null references businesses(place_id) on delete cascade,
  category      text not null,                 -- gbp / website / reachability
  signal        text not null,                 -- 'no_website', 'psi_mobile_poor', ...
  severity      text not null,                 -- critical / high / medium / low / info
  points        int not null,                  -- contribution to score
  finding       text not null,                 -- human-readable, pitch-ready sentence
  observed      jsonb                          -- the raw value that triggered it
);

create index if not exists idx_evidence_place  on score_evidence(place_id);
create index if not exists idx_evidence_signal on score_evidence(signal);

-- ---------------------------------------------------------------------------
-- Vertical baselines: per vertical + geo medians, so scoring is relative.
-- '23 reviews' means different things for an electrician in Carlsbad vs a
-- septic contractor in Ramona. Fixed thresholds produce a noisy list.
-- ---------------------------------------------------------------------------
create table if not exists vertical_baselines (
  id                uuid primary key default gen_random_uuid(),
  run_id            uuid references runs(id),
  vertical          text not null,
  geo_label         text not null,
  computed_at       timestamptz not null default now(),
  sample_size       int,
  median_reviews    numeric,
  p25_reviews       numeric,
  p75_reviews       numeric,
  median_rating     numeric,
  pct_with_website  numeric,
  median_psi_perf   numeric,
  unique (run_id, vertical, geo_label)
);

-- ---------------------------------------------------------------------------
-- Outreach: schema slot for v2. Not written to in v1, but defined now so the
-- pipeline doesn't need a migration when sending turns on.
-- ---------------------------------------------------------------------------
create table if not exists outreach (
  id                uuid primary key default gen_random_uuid(),
  place_id          text not null references businesses(place_id) on delete cascade,
  channel           text,                      -- email / phone / form / linkedin
  status            text default 'not_started',-- not_started/queued/sent/opened/replied/bounced/unsubscribed
  to_address        text,
  subject           text,
  body              text,
  sent_at           timestamptz,
  replied_at        timestamptz,
  unsubscribed_at   timestamptz,               -- CAN-SPAM: must be honored across all future runs
  suppressed        boolean default false,
  notes             text
);

create index if not exists idx_outreach_place  on outreach(place_id);
create index if not exists idx_outreach_status on outreach(status);

-- Suppression list, kept separate so it survives even if outreach rows are purged.
create table if not exists suppression (
  email       text primary key,
  reason      text,
  added_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Convenience view: the ranked worklist. This is what exports to CSV/Sheets.
-- ---------------------------------------------------------------------------
create or replace view v_lead_worklist as
select
  b.place_id,
  s.total_score,
  s.tier,
  s.headline_gap,
  b.name,
  b.vertical,
  b.city,
  b.phone,
  b.website_url,
  b.rating,
  b.review_count,
  w.emails_found,
  w.contact_page_url,
  w.psi_performance,
  w.cms_detected,
  w.has_localbusiness_schema,
  b.formatted_address,
  b.google_maps_uri,
  s.gbp_gap_score,
  s.website_gap_score,
  s.reachability_score,
  s.scored_at
from businesses b
join scores s            on s.place_id = b.place_id
left join website_enrichment w on w.place_id = b.place_id
order by s.total_score desc;


-- Latest completed-run lookup used by operational views.
create index if not exists idx_runs_finished_at
  on runs(finished_at desc)
  where finished_at is not null and dry_run = false;


-- Fast run-scoped lead ordering.
create index if not exists idx_scores_run_total
  on scores(run_id, total_score desc);

