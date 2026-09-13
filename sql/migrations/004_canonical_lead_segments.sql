begin;

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

        bool_or(
            e.signal like 'category_%'
        ) as category_opportunity

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

    coalesce(ef.category_opportunity, false)
        as category_opportunity,

    coalesce(ef.real_gap_count, 0)
        as real_gap_count,

    (
        b.last_review_days is not null
        and b.last_review_days <= 365
        and coalesce(b.review_count, 0) >= vb.median_reviews
        and coalesce(ef.real_gap_count, 0) >= 2
    ) as established

from v_latest_score s
join businesses b
  on b.place_id = s.place_id

left join vertical_baselines vb
  on vb.vertical = b.vertical
 and vb.run_id = s.run_id

left join evidence_flags ef
  on ef.place_id = s.place_id;

commit;
