BEGIN;

-- Canonical operational run: newest successfully completed real run.
CREATE OR REPLACE VIEW v_latest_completed_run AS
SELECT
    id,
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
    notes
FROM runs
WHERE finished_at IS NOT NULL
  AND dry_run = false
ORDER BY finished_at DESC, started_at DESC
LIMIT 1;


-- Operational scores must come ONLY from the latest completed run.
-- Historical scores remain preserved in the scores table.
CREATE OR REPLACE VIEW v_latest_score AS
SELECT
    s.id AS score_id,
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
JOIN v_latest_completed_run r
  ON r.id = s.run_id;


-- Worklist must also be operational/latest-run only.
CREATE OR REPLACE VIEW v_lead_worklist AS
SELECT
    b.place_id,
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
JOIN v_latest_score s
  ON s.place_id = b.place_id
LEFT JOIN website_enrichment w
  ON w.place_id = b.place_id
ORDER BY s.total_score DESC;


-- Supporting indexes for run-scoped dashboard/reporting queries.
CREATE INDEX IF NOT EXISTS idx_runs_finished_at
    ON runs (finished_at DESC)
    WHERE finished_at IS NOT NULL AND dry_run = false;

CREATE INDEX IF NOT EXISTS idx_scores_run_total
    ON scores (run_id, total_score DESC);

COMMIT;
