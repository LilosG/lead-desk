create table if not exists prospect_demo_media (
  id              uuid primary key default gen_random_uuid(),
  place_id        text not null references businesses(place_id) on delete cascade,
  role            text not null,
  source          text not null default 'generated',
  model           text,
  prompt_version  text,
  prompt_text     text,
  storage_path    text not null,
  public_url      text not null,
  created_at      timestamptz not null default now(),
  constraint prospect_demo_media_role_valid
    check (role in ('hero','work','secondary')),
  constraint prospect_demo_media_source_valid
    check (source in ('generated','manual'))
);

create index if not exists idx_prospect_demo_media_place
  on prospect_demo_media(place_id, created_at desc);
