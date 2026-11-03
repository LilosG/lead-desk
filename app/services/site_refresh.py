"""Bring one lead's site checks up to date just before its audit is built.

Sweeps stay shallow so they stay fast. The pages a report quotes (service page
word counts, titles) and any missing speed test are fetched here, once, for the
leads that actually get a report.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.repositories.prospects import ProspectRepository
from app.services.pipeline_bridge import load

FRESH_FOR = timedelta(days=14)
TIME_BUDGET_S = 45
_PSI_FIELDS = ("psi_performance", "psi_seo", "psi_accessibility", "psi_best_practices",
               "psi_lcp_ms", "psi_cls", "psi_mobile_friendly", "raw_psi_payload")


def _is_fresh(audit: dict[str, Any], now: datetime) -> bool:
    signals = audit.get("site_signals") or {}
    checked = signals.get("checked_at")
    if signals.get("page_samples") is None or not checked:
        return False
    return now - datetime.fromisoformat(checked) < FRESH_FOR


def site_url(prospect: dict[str, Any], audit: dict[str, Any]) -> str | None:
    if prospect.get("website_url"):
        return prospect["website_url"]
    if audit.get("site_source") in ("found", "manual"):
        return audit.get("resolved_url")
    return None


class SiteRefresher:
    def __init__(self, repository: ProspectRepository):
        self.repository = repository

    def __call__(self, prospect: dict[str, Any]) -> None:
        place_id = prospect["place_id"]
        audit = self.repository.get_website_audit(place_id) or {}
        url = site_url(prospect, audit)
        needs_speed = audit.get("psi_performance") is None
        if not url or not audit.get("is_reachable"):
            return
        if _is_fresh(audit, datetime.now(timezone.utc)) and not needs_speed:
            return

        enrich = load("enrich")
        config = load("config")
        # Threads can't be cancelled, so a slow site is abandoned, not waited for.
        pool = ThreadPoolExecutor(max_workers=2)
        crawl = pool.submit(enrich.crawl_site, {**prospect, "website_url": url}, None, True)
        speed = (pool.submit(enrich.run_psi, audit.get("resolved_url") or url,
                             config.GOOGLE_API_KEY, "mobile", TIME_BUDGET_S - 5)
                 if needs_speed else None)
        changes: dict[str, Any] = {}
        try:
            found = crawl.result(timeout=TIME_BUDGET_S)
            if found.is_reachable and found.site_signals:
                changes["site_signals"] = found.site_signals
            if speed is not None:
                measured = enrich.apply_psi(enrich.SiteFindings(), speed.result(timeout=TIME_BUDGET_S))
                if measured.psi_performance is not None:
                    data = asdict(measured)
                    changes.update({key: data[key] for key in _PSI_FIELDS})
        except FutureTimeout:
            pass
        finally:
            pool.shutdown(wait=False)
        self.repository.save_site_refresh(place_id, changes)
