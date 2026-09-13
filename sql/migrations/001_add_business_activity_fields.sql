BEGIN;

ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS last_review_days integer,
    ADD COLUMN IF NOT EXISTS recent_reviews_90d integer;

ALTER TABLE businesses
    DROP CONSTRAINT IF EXISTS businesses_last_review_days_nonnegative;

ALTER TABLE businesses
    ADD CONSTRAINT businesses_last_review_days_nonnegative
    CHECK (last_review_days IS NULL OR last_review_days >= 0);

ALTER TABLE businesses
    DROP CONSTRAINT IF EXISTS businesses_recent_reviews_90d_nonnegative;

ALTER TABLE businesses
    ADD CONSTRAINT businesses_recent_reviews_90d_nonnegative
    CHECK (recent_reviews_90d IS NULL OR recent_reviews_90d >= 0);

COMMIT;
