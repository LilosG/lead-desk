"""
Orchestrator — the single entry point.

  python3 run.py --dry-run                      # cost estimate, zero API calls
  python3 run.py --verticals electrician        # full pilot
  python3 run.py --verticals electrician --no-db --limit 40   # local test, CSV only
  python3 run.py --rescore-from discovered.json # re-score cached data, free
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict

import config as C
import discover
import enrich as E
import scoring as S


def log(msg=""):
    print(msg, flush=True)


def export_csv(businesses: list, enrichment: dict, scored: list, path: str) -> None:
    by_id = {b["place_id"]: b for b in businesses}
    cols = [
        "rank", "tier", "score", "name", "vertical", "city", "phone", "email",
        "website", "rating", "reviews", "psi_mobile", "cms", "has_schema",
        "headline_gap", "top_gaps", "address", "maps_url",
        "gbp_score", "site_score", "reach_score", "place_id",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, s in enumerate(scored, 1):
            b = by_id.get(s.place_id, {})
            e = enrichment.get(s.place_id)
            gaps = [x for x in s.evidence
                    if x.category != "reachability" and x.severity in ("critical", "high")]
            w.writerow({
                "rank": i, "tier": s.tier, "score": s.total_score,
                "name": b.get("name"), "vertical": b.get("vertical"),
                "city": b.get("city"), "phone": b.get("phone"),
                "email": (getattr(e, "emails_found", []) or [None])[0] if e else None,
                "website": b.get("website_url"),
                "rating": b.get("rating"), "reviews": b.get("review_count"),
                "psi_mobile": getattr(e, "psi_performance", None) if e else None,
                "cms": getattr(e, "cms_detected", None) if e else None,
                "has_schema": getattr(e, "has_localbusiness_schema", None) if e else None,
                "headline_gap": s.headline_gap,
                "top_gaps": " | ".join(x.signal for x in gaps[:6]),
                "address": b.get("formatted_address"),
                "maps_url": b.get("google_maps_uri"),
                "gbp_score": s.gbp_gap_score, "site_score": s.website_gap_score,
                "reach_score": s.reachability_score, "place_id": s.place_id,
            })


def summarize(scored: list, businesses: list, baselines: dict) -> None:
    by_id = {b["place_id"]: b for b in businesses}
    tiers: dict = {}
    for s in scored:
        tiers[s.tier] = tiers.get(s.tier, 0) + 1

    log("\n" + "=" * 78)
    log("BASELINES (per vertical, this run)")
    for v, b in baselines.items():
        log(f"  {v:<16} n={b.sample_size:<4} median_reviews={b.median_reviews:<6.0f} "
            f"median_rating={b.median_rating:<4.1f} with_website={b.pct_with_website:.0f}%")

    log("\nTIER DISTRIBUTION")
    for t in ("A", "B", "C", "D"):
        n = tiers.get(t, 0)
        pct = (n / len(scored) * 100) if scored else 0
        log(f"  {t}: {n:>4}  ({pct:>4.1f}%)  {'#' * int(pct / 2)}")

    reachable = sum(1 for s in scored if s.reachability_score >= 30)
    with_email = sum(1 for s in scored if any(
        e.signal == "email_found" for e in s.evidence))
    log(f"\nREACHABILITY: {reachable}/{len(scored)} workable "
        f"({reachable / len(scored) * 100:.0f}%), {with_email} with a direct email")

    log("\nTOP 15 LEADS")
    log("-" * 78)
    for i, s in enumerate(scored[:15], 1):
        b = by_id.get(s.place_id, {})
        log(f"{i:>2}. [{s.tier}] {s.total_score:>3}  {(b.get('name') or '?')[:38]:<38} "
            f"{(b.get('city') or ''):<14} {b.get('review_count') or 0:>4}rev")
        log(f"      → {s.headline_gap[:100]}")
    log("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verticals", nargs="*", default=C.PILOT_VERTICALS)
    ap.add_argument("--cities", nargs="*", default=None)
    ap.add_argument("--grid", action="store_true", help="lat/lng grid sweep instead of city queries")
    ap.add_argument("--dry-run", action="store_true", help="cost estimate only, no API calls")
    ap.add_argument("--no-db", action="store_true", help="skip PostgreSQL, CSV only")
    ap.add_argument("--no-psi", action="store_true", help="skip PageSpeed (much faster)")
    ap.add_argument("--psi-limit", type=int, default=None, help="only PSI the top N sites")
    ap.add_argument("--limit", type=int, default=None, help="cap businesses (testing)")
    ap.add_argument("--rescore-from", default=None, help="re-score a cached discovered.json")
    ap.add_argument("--out", default="leads.csv")
    args = ap.parse_args()

    if args.dry_run:
        os.execv(sys.executable,
                 [sys.executable, "discover.py", "--dry-run",
                  *(["--grid"] if args.grid else []),
                  "--verticals", *args.verticals])

    ledger = discover.CostLedger()
    store = None
    run_id = None

    if not args.no_db:
        from store import PostgresStore
        store = PostgresStore()
        if not store.ping():
            log("!! PostgreSQL unreachable or schema not applied. Apply schema.sql first,")
            log("   or re-run with --no-db to work from CSV only.")
            return 1
        run_id = store.start_run(
            C.GEO_LABEL, args.verticals,
            len(discover.build_grid(C.GEO_BBOX, C.GRID_SPACING_KM)),
            notes=f"model={C.MODEL_VERSION}",
        )
        log(f"run_id={run_id}")

    # -- 1. discover ---------------------------------------------------------
    if args.rescore_from:
        log(f"loading cached businesses from {args.rescore_from} (no API calls)")
        with open(args.rescore_from) as fh:
            businesses = json.load(fh)
    else:
        log(f"DISCOVERY — {C.GEO_LABEL} — {args.verticals}")
        found, ledger = discover.sweep(
            args.verticals, cities=args.cities, use_grid=args.grid,
            ledger=ledger, progress=log,
        )
        businesses = list(found.values())
        with open("discovered.json", "w") as fh:
            json.dump(businesses, fh, indent=2, default=str)
        log(f"\n{len(businesses)} unique businesses | {ledger.summary()}")

    if args.limit:
        businesses = businesses[: args.limit]
        log(f"limited to {len(businesses)} for testing")

    if not businesses:
        log("No businesses found. Check API key and query terms.")
        return 1

    # -- 2. enrich -----------------------------------------------------------
    log("\nENRICHMENT")
    enrichment = E.enrich_all(
        businesses, with_psi=not args.no_psi,
        psi_limit=args.psi_limit, progress=log,
    )

    # -- 3. score ------------------------------------------------------------
    log("\nSCORING")
    scored, baselines = S.score_all(businesses, enrichment, C.GEO_LABEL)
    summarize(scored, businesses, baselines)

    # -- 4. persist ----------------------------------------------------------
    export_csv(businesses, enrichment, scored, args.out)
    log(f"\nCSV -> {args.out}")

    if store and run_id:
        log("writing to PostgreSQL...")
        store.save_businesses(businesses, run_id)
        store.save_enrichment(enrichment)
        store.save_baselines(baselines, run_id)
        store.save_scores(scored, run_id)
        store.finish_run(run_id, ledger, ledger.est_usd_after_free_tier())
        log(f"saved. run_id={run_id}")

    log(f"\nAPI cost this run: ${ledger.est_usd_after_free_tier():.2f} "
        f"(gross ${ledger.est_usd():.2f} before free tier)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
