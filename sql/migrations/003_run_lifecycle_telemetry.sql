BEGIN;

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS stage text,
    ADD COLUMN IF NOT EXISTS businesses_discovered integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS websites_crawled integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS psi_completed integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS discovery_finished_at timestamptz,
    ADD COLUMN IF NOT EXISTS crawl_finished_at timestamptz,
    ADD COLUMN IF NOT EXISTS psi_finished_at timestamptz;

UPDATE runs
SET status = 'completed',
    stage = COALESCE(stage, 'completed')
WHERE finished_at IS NOT NULL;

ALTER TABLE runs
    DROP CONSTRAINT IF EXISTS runs_status_valid;

ALTER TABLE runs
    ADD CONSTRAINT runs_status_valid
    CHECK (status IN ('running', 'completed', 'failed', 'abandoned'));

ALTER TABLE runs
    DROP CONSTRAINT IF EXISTS runs_stage_valid;

ALTER TABLE runs
    ADD CONSTRAINT runs_stage_valid
    CHECK (
        stage IS NULL OR
        stage IN ('discovery', 'crawl', 'psi', 'finalize', 'completed')
    );

ALTER TABLE runs
    DROP CONSTRAINT IF EXISTS runs_businesses_discovered_nonnegative;

ALTER TABLE runs
    ADD CONSTRAINT runs_businesses_discovered_nonnegative
    CHECK (businesses_discovered >= 0);

ALTER TABLE runs
    DROP CONSTRAINT IF EXISTS runs_websites_crawled_nonnegative;

ALTER TABLE runs
    ADD CONSTRAINT runs_websites_crawled_nonnegative
    CHECK (websites_crawled >= 0);

ALTER TABLE runs
    DROP CONSTRAINT IF EXISTS runs_psi_completed_nonnegative;

ALTER TABLE runs
    ADD CONSTRAINT runs_psi_completed_nonnegative
    CHECK (psi_completed >= 0);

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
WHERE finished_at IS NOT NULL
  AND dry_run = false
  AND status = 'completed'
ORDER BY finished_at DESC, started_at DESC
LIMIT 1;

COMMIT;
