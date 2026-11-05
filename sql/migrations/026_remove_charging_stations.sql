-- An "ev charger installer" search brought public charging stations in as
-- electricians. They aren't businesses to pitch, so they come out. Anything
-- already contacted stays, and so does anything Google also calls an electrician.

begin;

delete from businesses b
where not ('electrician' = any(coalesce(b.types, '{}')) or b.primary_type = 'electrician')
  and (
        b.primary_type = 'electric_vehicle_charging_station'
        or 'electric_vehicle_charging_station' = any(coalesce(b.types, '{}'))
        or b.name ~* '(supercharger|charging station|destination charger)'
      )
  and not exists (
        select 1 from outreach_queue q
        where q.place_id = b.place_id
          and (q.contacted_at is not null or q.gmail_draft_id is not null)
      );

commit;
