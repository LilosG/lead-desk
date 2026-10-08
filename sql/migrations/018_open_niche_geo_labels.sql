-- Open niche + open geo, and labels that explain leads instead of filtering them.
--
-- * businesses.market: the searched market ("City, ST, USA") a business was
--   found in. Local comparisons (review medians, competitors) use this, not a
--   fixed region.
-- * businesses.is_franchise: franchises are kept and labelled, not dropped.
-- * website_enrichment: niche-aware page detection and online booking.
-- * scores.labels: plain labels computed at scoring time (established, no
--   website, phone only, verify first, franchise, ...). NULL means the score
--   came from the v1 model, which had no labels.

begin;

alter table businesses
    add column if not exists market text,
    add column if not exists is_franchise boolean not null default false;

create index if not exists idx_businesses_market on businesses(market);

alter table website_enrichment
    add column if not exists offering_page_count integer,
    add column if not exists offering_titles text[],
    add column if not exists location_page_count integer,
    add column if not exists sitemap_url_count integer,
    add column if not exists has_online_booking boolean,
    add column if not exists booking_provider text;

alter table scores
    add column if not exists labels text[],
    add column if not exists market text;

create index if not exists idx_scores_labels on scores using gin (labels);

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
    s.market
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

create or replace view v_lead_segments as
with evidence_flags as (
    select
        s.place_id,
        count(*) filter (
            where e.signal in (
                'no_localbusiness_schema',
                'no_city_pages',
                'no_service_pages',
                'psi_mobile_critical',
                'psi_mobile_poor',
                'thin_content',
                'template_builder',
                'no_contact_form',
                'no_ssl',
                'no_title',
                'category_generic',
                'category_mismatch',
                'no_website',
                'site_down',
                'no_services_listed',
                'no_business_description',
                'no_review_replies'
            )
        ) as real_gap_count,
        bool_or(e.signal like 'category_%') as category_opportunity
    from v_latest_score s
    left join score_evidence e
      on e.score_id = s.score_id
    group by s.place_id
)
select
    s.place_id,

    (
        b.last_review_days is not null
        and b.last_review_days <= 365
    ) as confirmed_trading,

    coalesce(ef.category_opportunity, false) as category_opportunity,

    coalesce(ef.real_gap_count, 0) as real_gap_count,

    case
        -- v2+ scores carry the label, computed against the lead's own niche
        -- AND market median.
        when s.labels is not null then 'established' = any(s.labels)
        -- v1 scores: original rule against the run's single niche baseline.
        else (
            b.last_review_days is not null
            and b.last_review_days <= 365
            and coalesce(b.review_count, 0) >= vb.median_reviews
            and coalesce(ef.real_gap_count, 0) >= 2
        )
    end as established,

    coalesce(s.labels, '{}'::text[]) as labels,
    coalesce(s.market, b.market) as market

from v_latest_score s
join businesses b
  on b.place_id = s.place_id
left join lateral (
    select vb1.median_reviews
    from vertical_baselines vb1
    where vb1.vertical = b.vertical
      and vb1.run_id = s.run_id
    order by vb1.computed_at desc
    limit 1
) vb on s.labels is null
left join evidence_flags ef
  on ef.place_id = s.place_id;

commit;
