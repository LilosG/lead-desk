# LILOs Lead Desk — Hyperagent Migration Starter

This bundle was extracted directly from the Hyperagent `Lead Desk` export.

## Preserved
- Lead Desk system prompt
- `lilos-lead-aggregator` Python pipeline
- existing scoring and verification logic
- current Supabase/PostgREST schema and views, preserved under `sql/`
- current dashboard generator
- tests
- optional DataForSEO GBP enrichment skill

## Migration rule
Do not alter scoring, claim verification, paging, crawler durability, suppression, or established-segment behavior until the existing pipeline has been reproduced successfully outside Hyperagent.

## Next migration step
The current `store.py` and `outreach.py` are still Supabase/PostgREST-oriented. They should be ported to local PostgreSQL only after PostgreSQL is running and the existing schema has been reviewed for Supabase-specific SQL.
