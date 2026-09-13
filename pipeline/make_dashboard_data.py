"""
Build dashboard_data.json from local pipeline output.

Reads discovered.json + enrichment_cache.json, scores everything, and flattens it
into the compact shape build_dashboard.py embeds in the HTML. Deliberately reads
LOCAL files rather than the database: local state is always the freshest, and a
partial database write (which has happened) would otherwise silently produce a
dashboard with missing findings.

Usage:
    python3 make_dashboard_data.py        # then: python3 build_dashboard.py
"""
from __future__ import annotations

import json
import statistics
import os
from dataclasses import fields

import config as C
import scoring as S
from enrich import SiteFindings

LIVE = {"active", "steady"}

# Signals that constitute "neglected marketing" for the established segment.
NEGLECT_SIGNALS = {
    "no_localbusiness_schema", "no_city_pages", "no_service_pages",
    "psi_mobile_critical", "psi_mobile_poor", "thin_content",
    "template_builder", "no_contact_form", "no_ssl", "no_title",
    "category_generic", "category_mismatch", "no_website", "site_down",
    "no_services_listed", "no_business_description", "no_review_replies",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def load_enrichment() -> dict:
    if not os.path.exists("enrichment_cache.json"):
        return {}
    valid = {f.name for f in fields(SiteFindings)}
    raw = json.load(open("enrichment_cache.json"))
    return {k: SiteFindings(**{a: b for a, b in v.items() if a in valid})
            for k, v in raw.items()}


def load_deep() -> dict:
    """Optional paid enrichment. Absent for most runs."""
    if not os.path.exists("gbp_deep_cache.json"):
        return {}
    return json.load(open("gbp_deep_cache.json"))


def main() -> int:
    businesses = json.load(open("discovered.json"))
    cache = load_enrichment()
    deep = load_deep()

    scored, baselines = S.score_all(businesses, cache, C.GEO_LABEL, deep)
    by_id = {b["place_id"]: b for b in businesses}
    # Per-vertical medians. This used to be
    # `list(baselines.values())[0].median_reviews` — an ARBITRARY vertical's
    # median applied to every business, so on the 2026-08-27 tri-vertical sweep
    # HVAC and roofing (local medians of 12) were judged against the plumber
    # median of 38, and the "established" count silently depended on dict
    # ordering. Same bug class as segment.py's hardcoded 'electrician'.
    med_by_vertical = {k: v.median_reviews for k, v in baselines.items()}
    med = (statistics.median(list(med_by_vertical.values()))
           if med_by_vertical else 0)

    rows = []
    for s in scored:
        b = by_id.get(s.place_id)
        if not b:
            continue
        w = cache.get(s.place_id)
        emails = list(getattr(w, "emails_found", None) or []) if w else []

        findings = [e for e in s.evidence if e.category != "reachability"]
        findings.sort(key=lambda x: (SEVERITY_ORDER.get(x.severity, 9), -x.points))
        hits = [e for e in s.evidence if e.signal in NEGLECT_SIGNALS]

        rows.append({
            "id": s.place_id,
            "n": b.get("name"),
            "c": b.get("city") or "",
            "p": b.get("phone"),
            "e": emails[0] if emails else None,
            "w": b.get("website_url"),
            "r": b.get("review_count") or 0,
            "g": float(b["rating"]) if b.get("rating") else None,
            "s": s.total_score,
            "t": s.tier,
            "h": s.headline_gap,
            "psi": getattr(w, "psi_performance", None) if w else None,
            "cms": getattr(w, "cms_detected", None) if w else None,
            "blocked": bool((getattr(w, "crawl_error", "") or "").startswith("blocked_")),
            "a": b.get("formatted_address"),
            "m": b.get("google_maps_uri"),
            "act": s.activity,
            "lrd": b.get("last_review_days"),
            "cat": b.get("primary_type"),
            "miscat": any(e.signal.startswith("category_") for e in s.evidence),
            "enriched": s.place_id in deep,
            # "Established" = demonstrably trading, at or above the local median on
            # reviews, and carrying at least two real gaps. This is the segment
            # most able to pay, and it's the dashboard's default view.
            "est": (s.activity in LIVE
                    and (b.get("review_count") or 0)
                        >= med_by_vertical.get(b.get("vertical"), med)
                    and len(hits) >= 2),
            "f": [{"s": e.severity, "t": e.finding} for e in findings[:8]],
        })

    rows.sort(key=lambda x: (-x["s"], -x["r"]))
    json.dump(rows, open("dashboard_data.json", "w"))

    print(f"rows          {len(rows)}")
    print(f"median reviews {med:.0f}")
    print(f"emailable     {sum(1 for r in rows if r['e'])}")
    print(f"no website    {sum(1 for r in rows if not r['w'])}")
    print(f"confirmed live {sum(1 for r in rows if r['act'] in LIVE)}")
    print(f"established   {sum(1 for r in rows if r['est'])}")
    print(f"wrong category {sum(1 for r in rows if r['miscat'])}")
    print(f"deep-enriched {sum(1 for r in rows if r['enriched'])}")
    print("\n-> dashboard_data.json  (now run: python3 build_dashboard.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
