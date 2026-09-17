create table if not exists prospect_demo_sites (
  id                  uuid primary key default gen_random_uuid(),
  place_id            text not null references businesses(place_id) on delete cascade,
  demo_version        integer not null default 1,
  status              text not null default 'ready_for_review',
  template_key        text not null,
  slug                text not null unique,
  source_snapshot     jsonb not null,
  content_snapshot    jsonb not null,
  brand_snapshot      jsonb not null,
  html_document       text not null,
  published_path      text,
  public_url          text,
  build_error         text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  published_at        timestamptz,
  constraint prospect_demo_sites_status_valid
    check (status in ('ready_for_review','published','build_failed','archived'))
);

create index if not exists idx_prospect_demo_sites_place
  on prospect_demo_sites(place_id, created_at desc);

create index if not exists idx_prospect_demo_sites_status
  on prospect_demo_sites(status, updated_at desc);
