"""Re-score leads after we learn their real website.

Used by recheck_unlisted.py (sites found by name) and by the app's
"Set website" button (a site Mike links by hand). Either way the Google
profile still has no website, so the lead is scored on the real site plus a
'website_not_on_gbp' finding, never as "no website".
"""
from __future__ import annotations

import os
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

import config as C  # pipeline modules import each other by bare name
import enrich as E
import scoring as S
from store import PostgresStore


def save_rescored(store: PostgresStore, pairs: list[tuple[dict, Any]], label: str) -> int:
    """Score each (business row, SiteFindings) against its niche+market cohort and save."""
    if not pairs:
        return 0
    with psycopg.connect(store.dsn, row_factory=dict_row) as conn:
        cohort: list[dict] = []
        for vertical, market in {(b["vertical"], b["market"]) for b, _ in pairs}:
            cohort += conn.execute(
                "select * from businesses where vertical is not distinct from %s "
                "and market is not distinct from %s",
                (vertical, market),
            ).fetchall()
    baselines = S.compute_baselines(cohort or [dict(b) for b, _ in pairs])
    scored = []
    for b, f in pairs:
        base = S.baseline_for(baselines, b.get("vertical") or "unknown", b.get("market"))
        if base is not None:
            scored.append(S.score_lead(dict(b), f, base))
    run_id = store.start_run(
        geo_label=label,
        verticals=sorted({b["vertical"] for b, _ in pairs if b.get("vertical")}),
        grid_points=0,
        notes=f"{label}: {len(pairs)} lead(s)",
        kind="rescore",
    )
    store.save_enrichment({b["place_id"]: f for b, f in pairs if f is not None})
    store.save_scores(scored, run_id)
    store.finish_run(run_id)
    return len(scored)


def rescore_lead(place_id: str, label: str, dsn: str | None = None) -> None:
    """Re-grade one lead after a manual change (an email added, a site checked)."""
    from rescore import findings_from_row

    store = PostgresStore(dsn or os.environ.get("DATABASE_URL"))
    with psycopg.connect(store.dsn, row_factory=dict_row) as conn:
        business = conn.execute(
            "select * from businesses where place_id = %s", (place_id,)
        ).fetchone()
        row = conn.execute(
            "select * from website_enrichment where place_id = %s", (place_id,)
        ).fetchone()
    if business is None:
        raise WebsiteError("prospect not found")
    found = findings_from_row(row, business.get("manual_email"))
    save_rescored(store, [(business, found)], label)


class WebsiteError(ValueError):
    pass


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise WebsiteError("enter a website address")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    if not re.match(r"^https?://[^/\s]+\.[^/\s]+", url):
        raise WebsiteError("that doesn't look like a website address")
    return url


def set_manual_website(place_id: str, url: str, dsn: str | None = None,
                       with_psi: bool = True) -> dict:
    """Crawl (and optionally speed-test) a site Mike says is this lead's, then re-score."""
    url = normalize_url(url)
    store = PostgresStore(dsn or os.environ.get("DATABASE_URL"))
    with psycopg.connect(store.dsn, row_factory=dict_row) as conn:
        business = conn.execute(
            "select * from businesses where place_id = %s", (place_id,)
        ).fetchone()
    if business is None:
        raise WebsiteError("prospect not found")

    findings = E.crawl_site({**business, "website_url": url})
    if not findings.is_reachable:
        raise WebsiteError(
            f"couldn't load {url} ({findings.crawl_error or findings.http_status}); "
            "check the address and try again"
        )
    findings.site_source = "manual"
    if with_psi:
        try:
            E.apply_psi(findings, E.run_psi(findings.resolved_url or url, C.GOOGLE_API_KEY))
        except Exception:
            pass  # speed test is a bonus; the crawl is what matters

    save_rescored(store, [(business, findings)], "Website set by hand")
    return {
        "place_id": place_id,
        "website_url": findings.resolved_url or url,
        "mobile_speed": findings.psi_performance,
        "title": findings.title,
    }
