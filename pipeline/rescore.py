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
import json
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


# What a re-read is allowed to change. PageSpeed results and manual entries stay.
REFRESHED_SIGNALS = ("ev_service", "ev_strength", "ev_page_path", "ev_page_title",
                     "ev_brands", "ev_commercial", "owner_name")


def apply_site_facts(dsn: str, results: list[E.SiteFindings | None]) -> int:
    """Store what a re-read learned. Sites that can't be read keep what's on file."""
    readable = [f for f in results if f and f.is_reachable and f.site_signals]
    with psycopg.connect(dsn) as conn:
        for found in readable:
            facts = {key: found.site_signals.get(key) for key in REFRESHED_SIGNALS}
            conn.execute(
                """
                update website_enrichment
                set site_signals = coalesce(site_signals, '{}'::jsonb) || %s::jsonb,
                    emails_found = case when cardinality(coalesce(emails_found, '{}')) = 0
                                        then %s::text[] else emails_found end
                where place_id = %s
                """,
                (json.dumps(facts), found.emails_found, found.place_id),
            )
    return len(readable)


def reread_sites(dsn: str, where: str, params: tuple) -> int:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        businesses = conn.execute(
            f"""
            select b.*
            from businesses b
            join website_enrichment w on w.place_id = b.place_id
            where b.website_url is not null and w.site_source = 'gbp' and {where}
            """,
            params,
        ).fetchall()
    if not businesses:
        return 0
    print(f"re-reading {len(businesses)} sites...", flush=True)
    with ProcessPoolExecutor(max_workers=C.CRAWL_MAX_CONCURRENT) as pool:
        return apply_site_facts(dsn, list(pool.map(read_site, [dict(b) for b in businesses])))


def refresh_ev_signal(dsn: str, niche: str) -> int:
    """Re-read one niche's sites for EV detail, owner names and any missing email."""
    return reread_sites(dsn, "b.vertical = %s", (niche,))


def recrawl_missing_email(dsn: str) -> int:
    """Leads crawled before the current email finder, whose sites do load."""
    return reread_sites(
        dsn,
        "cardinality(coalesce(w.emails_found, '{}')) = 0 and coalesce(w.is_reachable, false)",
        (),
    )


def rerank_emails(dsn: str) -> int:
    """Put stored addresses in the current best-first order. Crawls nothing."""
    changed = 0
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(
            "select place_id, emails_found from website_enrichment "
            "where cardinality(coalesce(emails_found, '{}')) > 1"
        ).fetchall()
        for row in rows:
            ranked = E.rank_emails(row["emails_found"])
            if ranked != row["emails_found"]:
                conn.execute("update website_enrichment set emails_found = %s where place_id = %s",
                             (ranked, row["place_id"]))
                changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recrawl-stalled", action="store_true")
    ap.add_argument("--refresh-ev-signal", metavar="NICHE",
                    help="re-read one niche's sites for EV detail and owner names")
    ap.add_argument("--recrawl-missing-email", action="store_true",
                    help="re-read working sites that have no email on file")
    ap.add_argument("--rerank-emails", action="store_true",
                    help="put stored addresses in best-first order, without crawling")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")
    if args.recrawl_stalled:
        print(f"recovered {recrawl_stalled(dsn)} sites")
    if args.refresh_ev_signal:
        print(f"updated {refresh_ev_signal(dsn, args.refresh_ev_signal)} sites")
    if args.recrawl_missing_email:
        print(f"re-read {recrawl_missing_email(dsn)} sites")
    if args.rerank_emails:
        print(f"re-ordered emails on {rerank_emails(dsn)} leads")
    counts = rescore_all(dsn)
    labels = C.QUALIFICATION_LABELS
    print(f"\nre-scored {sum(counts.values())} leads with model {C.MODEL_VERSION}")
    for key in labels:
        print(f"  {labels[key]:<24}{counts.get(key, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
