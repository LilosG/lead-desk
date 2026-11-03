-- Scoring model v3: a fit score and a plain verdict on every lead, the audit's
-- depth checks, and a way to clear the two things that used to dead-end a lead
-- (a bot-blocked site nobody could sign off, and a good lead with no email).

begin;

alter table scores
    add column if not exists fit_score integer,
    add column if not exists qualification text,
    add column if not exists qualification_reasons text[];

create index if not exists idx_scores_qualification on scores(qualification);

alter table website_enrichment
    add column if not exists site_signals jsonb;

alter table runs
    add column if not exists discovery_stats jsonb,
    -- 'rescore' runs re-grade stored leads. They spend nothing and stay off the Runs list.
    add column if not exists kind text not null default 'sweep';

alter table businesses
    add column if not exists manual_email text,
    add column if not exists site_checked_at timestamptz;

-- Columns are appended: create or replace can't reorder a view.
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
    s.headline_gap,
    s.labels,
    s.market,
    s.fit_score,
    s.qualification,
    s.qualification_reasons
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

-- An email Mike found by hand comes first and survives every re-crawl.
create or replace view v_lead_worklist as
select b.place_id,
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
    case
        when b.manual_email is not null
            then array_prepend(b.manual_email, array_remove(coalesce(w.emails_found, '{}'::text[]), b.manual_email))
        else w.emails_found
    end as emails_found,
    w.contact_page_url,
    w.psi_performance,
    w.cms_detected,
    w.has_localbusiness_schema,
    b.formatted_address,
    b.google_maps_uri,
    s.gbp_gap_score,
    s.website_gap_score,
    s.reachability_score,
    s.scored_at,
    s.fit_score,
    s.qualification,
    s.qualification_reasons
from businesses b
join v_latest_score s
  on s.place_id = b.place_id
left join website_enrichment w
  on w.place_id = b.place_id
order by s.total_score desc;

-- Once Mike has looked at a blocked site, it no longer needs a manual check.
create or replace view v_lead_findings as
select s.place_id,
    string_agg(e.finding, '  •  '::text order by (
        case e.severity
            when 'critical'::text then 1
            when 'high'::text then 2
            when 'medium'::text then 3
            when 'low'::text then 4
            else 5
        end), e.points desc) filter (where e.category <> 'reachability'::text) as what_to_fix,
    count(*) filter (where (e.severity = any (array['critical'::text, 'high'::text]))
                       and e.category <> 'reachability'::text) as major_issues,
    bool_or(e.signal = 'crawl_blocked'::text) and max(b.site_checked_at) is null as needs_manual_check
from v_latest_score s
join score_evidence e
  on e.score_id = s.score_id
join businesses b
  on b.place_id = s.place_id
group by s.place_id;

commit;
