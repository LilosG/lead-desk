-- Lead Desk operational inventory is cumulative across completed sweeps.
--
-- A narrow city/vertical refresh must update that market slice without hiding
-- prospects scored by earlier completed runs. Keep the newest completed score
-- for each Google place rather than scoping the whole desk to one latest run.

create or replace view v_latest_score as
select distinct on (s.place_id)
    s.id as score_id,
    s.place_id,
    s.run_id,
    s.model_version,
    s.scored_at,
    s.total_score,
    s.gbp_gap_score,
    s.website_gap_score,
    s.reachability_score,
    s.tier,
    s.headline_gap
from scores s
join runs r
  on r.id = s.run_id
where r.finished_at is not null
  and r.dry_run = false
  and r.status = 'completed'
order by
    s.place_id,
    s.scored_at desc,
    r.finished_at desc,
    s.id desc;
