#!/usr/bin/env python3
"""Re-check leads saved as "no website" for a real site that just isn't on Google.

Older sweeps took Google's word for it: no website on the profile meant "no
website". This finds each business's own site by name, verifies it (phone, or
name + city, on the page), crawls it, and saves a fresh score so the lead,
its audit and its email say "website not on your Google listing" instead.

Run from the pipeline folder on the server:
    python recheck_unlisted.py                     # every market
    python recheck_unlisted.py --market "Ramona, CA, USA"
    python recheck_unlisted.py --dry-run           # report only, save nothing

No Google API calls; it only fetches the candidate websites themselves.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.rows import dict_row

import enrich as E
import scoring as S
from store import PostgresStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", help='e.g. "San Diego, CA, USA"; default: all markets')
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    store = PostgresStore()
    with psycopg.connect(store.dsn, row_factory=dict_row) as conn:
        where = "b.website_url is null and coalesce(we.site_source, 'gbp') <> 'found'"
        params: list = []
        if args.market:
            where += " and b.market = %s"
            params.append(args.market)
        targets = conn.execute(f"""
            select b.* from businesses b
            left join website_enrichment we on we.place_id = b.place_id
            join v_latest_score s on s.place_id = b.place_id
            where {where}
        """, params).fetchall()
        print(f"checking {len(targets)} lead(s) saved with no website on Google...")
        if not targets:
            return 0

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(E.crawl_unlisted, targets))
        found = [(b, f) for b, f in zip(targets, results) if f.site_source == "found"]
        for b, f in found:
            print(f"  found: {b['name']} -> {f.resolved_url}")
        print(f"{len(found)} of {len(targets)} have a real site that isn't on Google.")
        if not found or args.dry_run:
            return 0

        # Baselines from each found lead's own niche + market cohort.
        keys = {(b["vertical"], b["market"]) for b, _ in found}
        cohort: list[dict] = []
        for vertical, market in keys:
            cohort += conn.execute(
                "select * from businesses where vertical = %s and market is not distinct from %s",
                (vertical, market),
            ).fetchall()

    baselines = S.compute_baselines(cohort)
    scored = []
    for b, f in found:
        base = S.baseline_for(baselines, b.get("vertical") or "unknown", b.get("market"))
        if base is not None:
            scored.append(S.score_lead(dict(b), f, base))

    run_id = store.start_run(
        geo_label="Recheck: sites not on Google",
        verticals=sorted({b["vertical"] for b, _ in found if b.get("vertical")}),
        grid_points=0,
        notes=f"recheck_unlisted: {len(found)} site(s) found",
    )
    store.save_enrichment({b["place_id"]: f for b, f in found})
    store.save_scores(scored, run_id)
    store.finish_run(run_id)
    print(f"saved {len(scored)} updated lead(s). Regenerate their audits to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
