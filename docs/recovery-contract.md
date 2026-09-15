# Lead Desk recovery contract

This document records the existing behavioral contract that the production Lead Desk must preserve. It is not a new product specification and does not authorize scope expansion.

## Non-negotiable behavior

- Preserve deterministic scoring semantics and per-vertical baselines. Scoring weights do not change without explicit approval.
- Preserve suppression as authoritative for email outreach.
- Preserve human review and draft-first Gmail behavior. Lead Desk has no automatic cold-email send path.
- Preserve false-claim protections. Uncertain evidence produces claim-free copy rather than a negative assertion.
- Preserve WAF/access-control handling: 403, 429, 5xx, timeouts, bot blocks, and crawl failures are never evidence that a site is down or missing a feature.
- Preserve `nap_mismatch` and `no_photos` as unsafe-to-assert findings.
- Preserve Google review liveness semantics: returned reviews prove recent activity when recent, but old returned reviews do not prove dormancy.
- Preserve Places paging by repeating the original request parameters with `pageToken`.
- Preserve geographic bounding-box verification; Google `locationBias` is not a geofence.
- Preserve contact-email filtering that rejects unrelated developer/footer domains.
- Preserve durable crawl/run state and `blocked_` classifications so blocked crawls cannot become false `site_down` claims.
- Google sweep execution is enabled only through the staged worker path. Production validation on 2026-09-15 completed discovery, crawl, PageSpeed, scoring, and finalize successfully after the execution gate, discovery timestamp dependency, and city-input normalization were corrected.
- Partial sweeps refresh a market slice; they must never replace or hide prospect inventory from other completed market slices.

## Architecture rules

- PostgreSQL remains the durable source of application workflow state.
- Operational prospect inventory uses the newest score per prospect from completed non-dry-run sweeps. A single narrow latest run is not the market universe.
- Market geography and supported verticals remain centralized in `pipeline/config.py`; dashboard filter options and sweep configuration derive from that contract rather than from whichever rows happen to be visible in the latest run.
- Migrations are append-only, checksummed, transactional, and applied through `sql/migrate.py`.
- Cross-system side effects must be recoverable. Gmail draft creation records durable intent before the external call and reconciles ambiguous outcomes before any retry.
- External prospect URLs are untrusted input. Live verification does not access private, loopback, link-local, or otherwise non-public destinations.
- A passing frontend build is not evidence that the backend is production-ready; backend unit/regression checks and production-data parity are validated independently.
- No workaround, duplicate implementation, or parallel truth system may be introduced to bypass an existing contract.
