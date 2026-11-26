-- Dedicated MyElectricalPermit.com contractor Pro Credit & 3-for-1 campaign.
-- Keeps original Permit Packets (ev_permits) queue, rotation, and drafts untouched.

begin;

insert into campaigns (key, name, description, sort_order) values (
    'my_electrical_permit',
    'MyElectricalPermit.com',
    'Pay-per-packet residential permit plans (GIS site plan, single-line, NEC 220 load calc & UL cut sheets) with 1 free credit + 3-for-1 starter pack',
    3
)
on conflict (key) do update set
    name = excluded.name,
    description = excluded.description,
    sort_order = excluded.sort_order,
    active = true;

commit;
