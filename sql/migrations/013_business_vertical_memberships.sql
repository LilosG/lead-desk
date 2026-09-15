-- Preserve every vertical a Google place legitimately matches.
--
-- businesses.place_id remains the canonical business identity. The legacy
-- businesses.vertical column remains the deterministic primary vertical used by
-- scoring/output, while this relation records all market memberships so later
-- sweeps cannot erase an earlier vertical association.

create table business_vertical_memberships (
    place_id text not null references businesses(place_id) on delete cascade,
    vertical text not null,
    first_seen_run uuid references runs(id),
    last_seen_run uuid references runs(id),
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    primary key (place_id, vertical)
);

create index idx_business_vertical_memberships_vertical
    on business_vertical_memberships(vertical, place_id);

insert into business_vertical_memberships (
    place_id,
    vertical,
    first_seen_run,
    last_seen_run,
    first_seen_at,
    last_seen_at
)
select
    b.place_id,
    b.vertical,
    b.first_seen_run,
    b.last_seen_run,
    b.first_seen_at,
    b.last_seen_at
from businesses b
where b.vertical is not null
  and b.vertical <> ''
on conflict (place_id, vertical) do nothing;
