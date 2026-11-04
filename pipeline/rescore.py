#!/usr/bin/env python3
"""Re-grade every stored lead with the current scoring model. Spends nothing.

  python pipeline/rescore.py                    # re-score everything
  python pipeline/rescore.py --recrawl-stalled  # first re-crawl sites the old
                                                # batch limit wrongly quarantined

Uses stored Google data and crawl results; it makes no paid API calls. Results
land in a run of kind 'rescore', so they become each lead's latest score and
stay off the Runs list.
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import fields
from typing import Any

import psycopg
from psycopg.rows import dict_row

import config as C
import enrich as E
import scoring as S
from store import PostgresStore

_FINDING_FIELDS = {f.name for f in fields(E.SiteFindings)}


def findings_from_row(row: dict | None, manual_email: str | None = None) -> E.SiteFindings | None:
    """A stored website_enrichment row as the crawler's SiteFindings."""
    if row is None:
        return None
    found = E.SiteFindings(**{k: v for k, v in row.items()
                              if k in _FINDING_FIELDS and v is not None})
    if manual_email:
        found.emails_found = [manual_email] + [e for e in found.emails_found if e != manual_email]
    return found


def load_all(dsn: str) -> tuple[list[dict], dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        businesses = conn.execute(
            """
            select b.*
            from businesses b
            where exists (select 1 from scores s where s.place_id = b.place_id)
            """
        ).fetchall()
        rows = conn.execute("select * from website_enrichment").fetchall()
    enrichment = {r["place_id"]: r for r in rows}
    return businesses, enrichment


def rescore_all(dsn: str) -> dict[str, int]:
    active = PostgresStore(dsn).get_active_run()
    if active:
        raise SystemExit(f"a sweep is running ({active['id']}); rescore when it finishes")

    store = PostgresStore(dsn)
    businesses, rows = load_all(dsn)
    if not businesses:
        return {}
    baselines = S.compute_baselines(businesses)
    scored = []
    for b in businesses:
        base = S.baseline_for(baselines, b.get("vertical") or "unknown", b.get("market"))
        if base is None:
            continue
        found = findings_from_row(rows.get(b["place_id"]), b.get("manual_email"))
        scored.append(S.score_lead(dict(b), found, base))

    run_id = store.start_run(
        geo_label=f"Rescore (model {C.MODEL_VERSION})",
        verticals=sorted({b["vertical"] for b in businesses if b.get("vertical")}),
        grid_points=0,
        notes=f"Re-scored {len(scored)} stored leads",
        kind="rescore",
    )
    store.save_scores(scored, run_id)
    store.finish_run(run_id)

    counts: dict[str, int] = {}
    for lead in scored:
        counts[lead.qualification] = counts.get(lead.qualification, 0) + 1
    return counts


def recrawl_stalled(dsn: str) -> int:
    """Sites quarantined as blocked_crawl_hang get a real crawl."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        businesses = conn.execute(
            """
            select b.*
            from businesses b
            join website_enrichment w on w.place_id = b.place_id
            where w.crawl_error = 'blocked_crawl_hang'
            """
        ).fetchall()
    if not businesses:
        return 0
    print(f"re-crawling {len(businesses)} quarantined sites...", flush=True)
    with ProcessPoolExecutor(max_workers=C.CRAWL_MAX_CONCURRENT) as pool:
        results = list(pool.map(E.crawl_business, [dict(b) for b in businesses]))
    PostgresStore(dsn).save_enrichment({f.place_id: f for f in results})
    return sum(1 for f in results if f.crawl_error != "blocked_crawl_hang")


def read_site(business: dict[str, Any]) -> E.SiteFindings | None:
    """Crawl one site. A failure costs that site, not the rest of the batch."""
    try:
        return E.crawl_business(business)
    except Exception as exc:
        print(f"skipped {business.get('name')}: {exc}"[:200], flush=True)
        return None


def refresh_ev_signal(dsn: str, niche: str) -> int:
    """Re-read one niche's sites and record only whether they offer EV work.

    Sites that can't be read keep what's on file, and nothing else is rewritten,
    so PageSpeed results and manual entries stay as they are.
    """
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        businesses = conn.execute(
            """
            select b.*
            from businesses b
            join website_enrichment w on w.place_id = b.place_id
            where b.vertical = %s
              and b.website_url is not null
              and w.site_source = 'gbp'
            """,
            (niche,),
        ).fetchall()
    if not businesses:
        return 0
    print(f"re-reading {len(businesses)} {niche} sites...", flush=True)
    with ProcessPoolExecutor(max_workers=C.CRAWL_MAX_CONCURRENT) as pool:
        results = list(pool.map(read_site, [dict(b) for b in businesses]))
    readable = [f for f in results
                if f and f.is_reachable and "ev_service" in (f.site_signals or {})]
    with psycopg.connect(dsn) as conn:
        for found in readable:
            conn.execute(
                """
                update website_enrichment
                set site_signals = coalesce(site_signals, '{}'::jsonb)
                                   || jsonb_build_object('ev_service', %s::boolean)
                where place_id = %s
                """,
                (found.site_signals["ev_service"], found.place_id),
            )
    return len(readable)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recrawl-stalled", action="store_true")
    ap.add_argument("--refresh-ev-signal", metavar="NICHE",
                    help="re-read one niche's sites to record who offers EV work")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")
    if args.recrawl_stalled:
        print(f"recovered {recrawl_stalled(dsn)} sites")
    if args.refresh_ev_signal:
        print(f"updated {refresh_ev_signal(dsn, args.refresh_ev_signal)} sites")
    counts = rescore_all(dsn)
    labels = C.QUALIFICATION_LABELS
    print(f"\nre-scored {sum(counts.values())} leads with model {C.MODEL_VERSION}")
    for key in labels:
        print(f"  {labels[key]:<24}{counts.get(key, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
