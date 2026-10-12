-- Sites that exist but aren't linked on the Google profile.
--
-- website_enrichment.site_source: 'gbp' when the site came from the Google
-- profile, 'found' when the profile had none and the crawler found and
-- verified the business's own site by name (phone or name + city on the page).
-- Those leads get 'website_not_on_gbp' instead of a false "no website".

begin;

alter table website_enrichment
    add column if not exists site_source text not null default 'gbp';

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
                'no_review_replies',
                'website_not_on_gbp'
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
