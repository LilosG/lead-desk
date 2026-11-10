#!/usr/bin/env python3
"""Fill in permit_jobs and permit_job_pages for electricians already in the database.

Leads crawled before the Permit Packets campaign have only the EV signals. This
re-reads each electrician's own website (no paid APIs) and merges two keys into
website_enrichment.site_signals. Nothing else in the row changes, and scores are
never touched, so there is no need to rescore afterwards.

Run on the VPS. Look first with --dry-run, which prints what it would store and
writes nothing:

  cd /home/mike/lead-desk && set -a && . ./.env && set +a && \
    .venv/bin/python pipeline/backfill_permit_signals.py --dry-run --limit 20

Then for real, in batches (a lead that already has permit_jobs is skipped
unless --redo is passed, so repeating the command carries on where it stopped):

  cd /home/mike/lead-desk && set -a && . ./.env && set +a && \
    .venv/bin/python pipeline/backfill_permit_signals.py --limit 200
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import psycopg
from psycopg.rows import dict_row

import config as C
from rescore import read_site

PERMIT_KEYS = ("permit_jobs", "permit_job_pages")


def electricians_to_read(dsn: str, limit: int | None, redo: bool) -> list[dict[str, Any]]:
    """Electricians with a stored website, still missing the permit signals."""
    sql = """
        select b.*
        from businesses b
        join website_enrichment w on w.place_id = b.place_id
        where b.vertical = 'electrician'
          and b.website_url is not null
          and w.site_source = 'gbp'
    """
    if not redo:
        sql += " and not (coalesce(w.site_signals, '{}'::jsonb) ? 'permit_jobs')"
    sql += " order by b.place_id"
    params: tuple = ()
    if limit:
        sql += " limit %s"
        params = (limit,)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def permit_facts(found: Any) -> dict[str, Any] | None:
    """The two keys to store, or None when the site couldn't be read."""
    if not (found and found.is_reachable and found.site_signals):
        return None
    return {key: found.site_signals.get(key) for key in PERMIT_KEYS}


def store_facts(dsn: str, facts: dict[str, dict[str, Any]]) -> None:
    with psycopg.connect(dsn) as conn:
        for place_id, values in facts.items():
            conn.execute(
                """
                update website_enrichment
                set site_signals = coalesce(site_signals, '{}'::jsonb) || %s::jsonb
                where place_id = %s
                """,
                (json.dumps(values), place_id),
            )


def backfill(dsn: str, limit: int | None = None, dry_run: bool = False, redo: bool = False) -> dict[str, int]:
    businesses = electricians_to_read(dsn, limit, redo)
    print(f"re-reading {len(businesses)} electrician sites...", flush=True)
    if not businesses:
        return {"read": 0, "unreadable": 0, "with_jobs": 0}
    with ProcessPoolExecutor(max_workers=C.CRAWL_MAX_CONCURRENT) as pool:
        results = list(pool.map(read_site, businesses))
    facts: dict[str, dict[str, Any]] = {}
    for business, found in zip(businesses, results):
        values = permit_facts(found)
        if values is not None:
            facts[business["place_id"]] = values
            if dry_run:
                print(f"{business['name']}: {values['permit_jobs']} {values['permit_job_pages']}")
    if not dry_run:
        store_facts(dsn, facts)
    return {
        "read": len(facts),
        "unreadable": len(businesses) - len(facts),
        "with_jobs": sum(1 for v in facts.values() if v["permit_jobs"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="read at most this many sites")
    ap.add_argument("--dry-run", action="store_true", help="print what would be stored; write nothing")
    ap.add_argument("--redo", action="store_true", help="also re-read leads that already have permit_jobs")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")
    counts = backfill(dsn, args.limit, args.dry_run, args.redo)
    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {counts['read']} leads ({counts['with_jobs']} show permit work); "
          f"{counts['unreadable']} sites could not be read and were left as they were")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
