-- Lilos Growth — Lead Desk operational views
--
-- Canonicalized from the validated PostgreSQL production schema after
-- migrations 001-003. Operational lead views intentionally scope scoring
-- to the latest completed, non-dry-run sweep.
--
-- Migration history remains authoritative for upgrading existing databases.
-- This file represents the current state for clean installations.

-- ================================================================
-- v_latest_completed_run
-- ================================================================
create or replace view v_latest_completed_run as
SELECT id,
    started_at,
    finished_at,
    geo_label,
    verticals,
    grid_points,
    api_calls_search,
    api_calls_details,
    api_calls_psi,
    est_cost_usd,
    dry_run,
    notes,
    status,
    stage,
    businesses_discovered,
    websites_crawled,
    psi_completed,
    discovery_finished_at,
    crawl_finished_at,
    psi_finished_at
   FROM runs
  WHERE finished_at IS NOT NULL AND dry_run = false AND status = 'completed'::text
  ORDER BY finished_at DESC, started_at DESC
 LIMIT 1;

-- ================================================================
-- v_latest_score
-- ================================================================
create or replace view v_latest_score as
SELECT s.id AS score_id,
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
   FROM scores s
     JOIN v_latest_completed_run r ON r.id = s.run_id;

-- ================================================================
-- v_lead_findings
-- ================================================================
create or replace view v_lead_findings as
SELECT s.place_id,
    string_agg(e.finding, '  •  '::text ORDER BY (
        CASE e.severity
            WHEN 'critical'::text THEN 1
            WHEN 'high'::text THEN 2
            WHEN 'medium'::text THEN 3
            WHEN 'low'::text THEN 4
            ELSE 5
        END), e.points DESC) FILTER (WHERE e.category <> 'reachability'::text) AS what_to_fix,
    count(*) FILTER (WHERE (e.severity = ANY (ARRAY['critical'::text, 'high'::text])) AND e.category <> 'reachability'::text) AS major_issues,
    bool_or(e.signal = 'crawl_blocked'::text) AS needs_manual_check
   FROM v_latest_score s
     JOIN score_evidence e ON e.score_id = s.score_id
  GROUP BY s.place_id;

-- ================================================================
-- v_lead_worklist
-- ================================================================
create or replace view v_lead_worklist as
SELECT b.place_id,
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
    w.emails_found,
    w.contact_page_url,
    w.psi_performance,
    w.cms_detected,
    w.has_localbusiness_schema,
    b.formatted_address,
    b.google_maps_uri,
    s.gbp_gap_score,
    s.website_gap_score,
    s.reachability_score,
    s.scored_at
   FROM businesses b
     JOIN v_latest_score s ON s.place_id = b.place_id
     LEFT JOIN website_enrichment w ON w.place_id = b.place_id
  ORDER BY s.total_score DESC;

-- ================================================================
-- v_leads
-- ================================================================
create or replace view v_leads as
SELECT row_number() OVER (ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST) AS rank,
    s.tier,
    s.total_score AS score,
    b.name,
    b.city,
    b.phone,
    w.emails_found[1] AS email,
    b.review_count AS reviews,
    b.rating,
        CASE
            WHEN b.website_url IS NULL THEN 'NO WEBSITE'::text
            ELSE b.website_url
        END AS website,
    f.major_issues,
    s.headline_gap AS biggest_problem,
    f.what_to_fix,
    w.psi_performance AS mobile_speed,
    w.cms_detected AS built_on,
    w.has_localbusiness_schema AS has_schema,
    f.needs_manual_check,
    b.vertical,
    b.formatted_address AS address,
    b.google_maps_uri AS maps_link,
    b.place_id
   FROM v_latest_score s
     JOIN businesses b ON b.place_id = s.place_id
     LEFT JOIN website_enrichment w ON w.place_id = s.place_id
     LEFT JOIN v_lead_findings f ON f.place_id = s.place_id
  ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST;

-- ================================================================
-- v_leads_call_list
-- ================================================================
create or replace view v_leads_call_list as
SELECT row_number() OVER (ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST) AS rank,
    s.tier,
    s.total_score AS score,
    b.name,
    b.city,
    b.phone,
    b.review_count AS reviews,
    b.rating,
    s.headline_gap AS opening_line,
    f.what_to_fix,
    b.formatted_address AS address,
    b.google_maps_uri AS maps_link,
    b.place_id
   FROM v_latest_score s
     JOIN businesses b ON b.place_id = s.place_id
     LEFT JOIN website_enrichment w ON w.place_id = s.place_id
     LEFT JOIN v_lead_findings f ON f.place_id = s.place_id
  WHERE b.phone IS NOT NULL AND (w.emails_found IS NULL OR cardinality(w.emails_found) = 0)
  ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST;

-- ================================================================
-- v_leads_email_list
-- ================================================================
create or replace view v_leads_email_list as
SELECT row_number() OVER (ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST) AS rank,
    s.tier,
    s.total_score AS score,
    b.name,
    b.city,
    w.emails_found[1] AS email,
    w.emails_found AS all_emails,
    b.phone,
    b.review_count AS reviews,
    b.website_url AS website,
    s.headline_gap AS opening_line,
    f.what_to_fix,
    w.psi_performance AS mobile_speed,
    b.place_id
   FROM v_latest_score s
     JOIN businesses b ON b.place_id = s.place_id
     JOIN website_enrichment w ON w.place_id = s.place_id
     LEFT JOIN v_lead_findings f ON f.place_id = s.place_id
     LEFT JOIN outreach o ON o.place_id = s.place_id AND o.status <> 'not_started'::text
  WHERE cardinality(COALESCE(w.emails_found, '{}'::text[])) > 0 AND o.id IS NULL AND NOT (EXISTS ( SELECT 1
           FROM suppression sup
          WHERE sup.email = w.emails_found[1]))
  ORDER BY s.total_score DESC, b.review_count DESC NULLS LAST;

-- ================================================================
-- v_leads_top25
-- ================================================================
create or replace view v_leads_top25 as
SELECT rank,
    tier,
    score,
    name,
    city,
    phone,
    email,
    reviews,
    website,
    biggest_problem,
    what_to_fix
   FROM v_leads
 LIMIT 25;

-- ================================================================
-- v_leads_needs_check
-- ================================================================
create or replace view v_leads_needs_check as
SELECT b.name,
    b.city,
    b.phone,
    b.website_url,
    b.review_count AS reviews,
    w.http_status,
    w.crawl_error,
    s.total_score AS provisional_score
   FROM website_enrichment w
     JOIN businesses b ON b.place_id = w.place_id
     LEFT JOIN v_latest_score s ON s.place_id = w.place_id
  WHERE w.crawl_error ~~ 'blocked_%'::text
  ORDER BY b.review_count DESC NULLS LAST;

-- ================================================================
-- v_lead_audit_detail
-- ================================================================
create or replace view v_lead_audit_detail as
SELECT b.name,
    b.city,
    s.total_score AS score,
    s.tier,
    e.category,
    e.severity,
    e.points,
    e.finding,
    e.signal,
    e.observed,
    b.place_id
   FROM v_latest_score s
     JOIN businesses b ON b.place_id = s.place_id
     JOIN score_evidence e ON e.score_id = s.score_id
  ORDER BY s.total_score DESC, b.name, (
        CASE e.severity
            WHEN 'critical'::text THEN 1
            WHEN 'high'::text THEN 2
            WHEN 'medium'::text THEN 3
            WHEN 'low'::text THEN 4
            ELSE 5
        END);

-- ================================================================
-- v_run_summary
-- ================================================================
create or replace view v_run_summary as
SELECT r.id AS run_id,
    r.started_at,
    r.geo_label,
    array_to_string(r.verticals, ', '::text) AS verticals,
    count(DISTINCT sc.place_id) AS businesses_scored,
    count(*) FILTER (WHERE sc.tier = 'A'::text) AS tier_a,
    count(*) FILTER (WHERE sc.tier = 'B'::text) AS tier_b,
    count(*) FILTER (WHERE sc.tier = 'C'::text) AS tier_c,
    count(*) FILTER (WHERE sc.tier = 'D'::text) AS tier_d,
    round(avg(sc.total_score), 1) AS avg_score,
    r.api_calls_search AS search_calls,
    r.est_cost_usd AS cost_usd
   FROM runs r
     LEFT JOIN scores sc ON sc.run_id = r.id
  GROUP BY r.id, r.started_at, r.geo_label, r.verticals, r.api_calls_search, r.est_cost_usd
  ORDER BY r.started_at DESC;

-- ================================================================
-- v_market_snapshot
-- ================================================================
create or replace view v_market_snapshot as
SELECT b.vertical,
    b.city,
    count(*) AS businesses,
    count(*) FILTER (WHERE b.website_url IS NULL) AS no_website,
    round(100.0 * count(*) FILTER (WHERE b.website_url IS NULL)::numeric / NULLIF(count(*), 0)::numeric, 1) AS pct_no_website,
    round(avg(b.review_count), 1) AS avg_reviews,
    count(*) FILTER (WHERE s.tier = ANY (ARRAY['A'::text, 'B'::text])) AS good_leads
   FROM businesses b
     LEFT JOIN v_latest_score s ON s.place_id = b.place_id
  GROUP BY b.vertical, b.city
 HAVING count(*) >= 3
  ORDER BY (count(*) FILTER (WHERE s.tier = ANY (ARRAY['A'::text, 'B'::text]))) DESC, (round(100.0 * count(*) FILTER (WHERE b.website_url IS NULL)::numeric / NULLIF(count(*), 0)::numeric, 1)) DESC;

