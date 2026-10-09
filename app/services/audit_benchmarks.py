"""The parts of the audit that compare a business with its real local competitors.

Everything here is computed from data the sweep already collected for the
other businesses in the same niche and city (Google numbers plus each
competitor's crawled website), so every number in the report is specific to
this business and this market rather than a generic checklist item.

  benchmarks()      you vs. the local typical vs. the best nearby, per metric,
                    with a plain verdict (behind / on par / ahead);
  page_gaps()       offerings most competitors give their own page that this
                    site doesn't (from links on each competitor's homepage);
  search_snippet()  the title and description Google shows now, and a
                    suggested rewrite built only from the business's own facts.
"""
from __future__ import annotations

import re
from statistics import median
from typing import Any

from pipeline import verticals as vertical_config

MIN_PEERS = 5

# Niche labels that aren't a noun for the business itself.
_NOUN_OVERRIDES = {"auto repair": "auto repair shop", "hvac": "HVAC company",
                   "roofing": "roofing company", "landscaping": "landscaping company"}

# Offering words too broad to be a page someone searches for by name.
_GENERIC_WORDS = {
    "service", "treatment", "skin", "wellness", "medspa", "med-spa", "sculpt",
    "therapy", "condition", "practice", "practice-area", "search", "featured",
    "sold", "property", "properties", "buy", "sell", "repair", "install",
    "maintenance", "inspection", "upgrade", "emergency", "cleaning", "detail",
    "body", "paint", "pain", "back", "sports", "injury", "lip", "peel",
    "rejuvenation", "tightening", "smile", "cosmetic", "rental", "party",
    "replacement", "remodel", "trust", "will", "estate", "employment",
}


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _share(values: list[bool]) -> float | None:
    return sum(1 for v in values if v) / len(values) if values else None


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _days(value: float) -> str:
    n = int(round(value))
    return "today" if n == 0 else f"{n} day ago" if n == 1 else f"{n} days ago"


def _site_peers(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in peers if p.get("has_website") and p.get("is_reachable")]


def benchmarks(
    prospect: dict[str, Any],
    audit: dict[str, Any] | None,
    peers: list[dict[str, Any]] | None,
    *,
    offering_label: str,
) -> dict[str, Any] | None:
    peers = peers or []
    if len(peers) < MIN_PEERS:
        return None
    audit = audit or {}
    rows: list[dict[str, Any]] = []

    def add(metric: str, you: str, typical: str, best: str, verdict: str, note: str = "") -> None:
        rows.append({"metric": metric, "you": you, "typical": typical, "best": best,
                     "verdict": verdict, "note": note})

    # Google reviews
    count = _num(prospect.get("review_count"))
    counts = [_num(p.get("review_count")) or 0 for p in peers]
    if count is not None:
        # Same basis as the report's "typical" figure: everyone, this business included.
        mid = _median(counts + [count]) or 0
        rank = 1 + sum(1 for c in counts if c > count)
        verdict = "behind" if count < mid * 0.75 else "ahead" if count > mid * 1.25 else "on_par"
        add("Google reviews", f"{int(count):,}", f"{int(round(mid)):,}", f"{int(max(counts)):,}",
            verdict, f"#{rank} of {len(peers) + 1} nearby")

    # Google rating
    rating = _num(prospect.get("rating"))
    ratings = [r for r in (_num(p.get("rating")) for p in peers) if r is not None]
    if rating is not None and len(ratings) >= MIN_PEERS:
        mid = _median(ratings) or 0
        verdict = "behind" if rating < mid - 0.2 else "ahead" if rating > mid + 0.1 else "on_par"
        add("Google rating", f"{rating:.1f}", f"{mid:.1f}", f"{max(ratings):.1f}", verdict)

    # Review recency (Google returns the newest few reviews with dates)
    days = _num(prospect.get("last_review_days"))
    peer_days = [d for d in (_num(p.get("last_review_days")) for p in peers) if d is not None]
    if days is not None and len(peer_days) >= MIN_PEERS:
        mid = _median(peer_days) or 0
        verdict = "behind" if days > max(30, mid * 2) else "ahead" if days < mid else "on_par"
        add("Newest Google review", _days(days), _days(mid), _days(min(peer_days)), verdict)

    # Hours on Google
    hours = prospect.get("has_hours")
    peer_hours = [bool(p.get("has_hours")) for p in peers if p.get("has_hours") is not None]
    if hours is not None and len(peer_hours) >= MIN_PEERS:
        share = _share(peer_hours) or 0
        add("Hours on Google", "Yes" if hours else "No", f"{_pct(share)} have them", "",
            "on_par" if hours else ("behind" if share >= 0.5 else "on_par"))

    site_ok = bool(prospect.get("website_url")) and audit.get("is_reachable")
    site_peers = _site_peers(peers)

    if site_ok:
        # Mobile speed (only some competitors get a speed test)
        speed = _num(audit.get("psi_performance"))
        speeds = [s for s in (_num(p.get("psi_performance")) for p in site_peers) if s is not None]
        if speed is not None and len(speeds) >= MIN_PEERS:
            mid = _median(speeds) or 0
            verdict = "behind" if speed < mid - 10 else "ahead" if speed > mid + 10 else "on_par"
            add("Mobile speed score", f"{int(speed)}/100", f"{int(round(mid))}/100",
                f"{int(max(speeds))}/100", verdict, f"{len(speeds)} competitors tested")

        # Offering pages
        pages = _num(audit.get("offering_page_count"))
        peer_pages = [x for x in (_num(p.get("offering_page_count")) for p in site_peers) if x is not None]
        if pages is not None and len(peer_pages) >= MIN_PEERS:
            mid = _median(peer_pages) or 0
            verdict = ("behind" if (pages == 0 and mid >= 2) or pages < mid / 2
                       else "ahead" if pages > mid * 1.5 and pages >= 3 else "on_par")
            label = offering_label[:1].upper() + offering_label[1:]
            add(label, f"{int(pages)}", f"{int(round(mid))}", f"{int(max(peer_pages))}", verdict)

        # Online booking
        booking = audit.get("has_online_booking")
        peer_booking = [bool(p.get("has_online_booking")) for p in site_peers]
        if booking is not None and len(peer_booking) >= MIN_PEERS:
            share = _share(peer_booking) or 0
            add("Online booking", "Yes" if booking else "No", f"{_pct(share)} offer it", "",
                "ahead" if booking and share < 0.5 else "on_par" if booking or share < 0.4 else "behind")

        # Business markup
        schema = audit.get("has_localbusiness_schema")
        peer_schema = [bool(p.get("has_localbusiness_schema")) for p in site_peers
                       if p.get("has_localbusiness_schema") is not None]
        if schema is not None and len(peer_schema) >= MIN_PEERS:
            share = _share(peer_schema) or 0
            add("Business details for Google (schema)", "Yes" if schema else "No",
                f"{_pct(share)} have it", "",
                "on_par" if schema or share < 0.4 else "behind")

    if not rows:
        return None
    return {
        "sample_size": len(peers),
        "site_sample_size": len(site_peers),
        "rows": rows,
        "behind": sum(1 for r in rows if r["verdict"] == "behind"),
        "ahead": sum(1 for r in rows if r["verdict"] == "ahead"),
    }


def _titles(row: dict[str, Any]) -> list[str]:
    return [t for t in (row.get("offering_titles") or []) if isinstance(t, str) and t.strip()]


def page_gaps(
    prospect: dict[str, Any],
    audit: dict[str, Any] | None,
    peers: list[dict[str, Any]] | None,
    limit: int = 6,
) -> dict[str, Any] | None:
    """Offerings competitors link a page for from their homepage, that this site doesn't."""
    audit = audit or {}
    if not (prospect.get("website_url") and audit.get("is_reachable")):
        return None
    site_peers = [p for p in _site_peers(peers or []) if _titles(p)]
    if len(site_peers) < MIN_PEERS:
        return None

    profile = vertical_config.niche_profile(prospect.get("vertical"))
    words = [w.strip("-") for w in profile.get("offering_words", []) if w.strip("-") not in _GENERIC_WORDS]
    own = " ".join(_slug(t) for t in _titles(audit))

    gaps = []
    for word in words:
        if word in own:
            continue
        holders = [p for p in site_peers if any(word in _slug(t) for t in _titles(p))]
        if len(holders) < max(2, round(len(site_peers) * 0.25)):
            continue
        names: dict[str, int] = {}
        for p in holders:
            for t in _titles(p):
                if word in _slug(t):
                    key = " ".join(t.split())
                    names[key] = names.get(key, 0) + 1
                    break
        label = sorted(names.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]
        gaps.append({"word": word, "label": label, "count": len(holders)})

    # One gap per distinct label (e.g. "botox" and "dysport" -> "Botox & Dysport").
    seen: set[str] = set()
    unique = []
    for gap in sorted(gaps, key=lambda g: -g["count"]):
        key = gap["label"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append({"label": gap["label"], "count": gap["count"]})
    if not unique:
        return None
    return {
        "sample_size": len(site_peers),
        "gaps": unique[:limit],
        "yours": _titles(audit)[:8],
        "offering_label": profile["offering_label"],
    }


def _fit(parts: list[str], limit: int) -> str:
    out = ""
    for part in parts:
        if len(out) + len(part) > limit:
            break
        out += part
    return out


def search_snippet(
    prospect: dict[str, Any],
    audit: dict[str, Any] | None,
    clean_name: str,
) -> dict[str, Any] | None:
    """Current Google snippet and a suggested one, using only the business's own facts."""
    audit = audit or {}
    if not (prospect.get("website_url") and audit.get("is_reachable")):
        return None
    city, state = prospect.get("city"), prospect.get("state")
    place = ", ".join(p for p in [city, state] if p)
    niche = vertical_config.vertical_label(prospect.get("vertical") or "") or ""
    niche_title = " ".join(w[:1].upper() + w[1:] for w in niche.split())
    offerings = [" ".join(t.split()) for t in _titles(audit)][:3]

    focus = ""
    if offerings:
        focus = offerings[0] if len(offerings) == 1 else f"{offerings[0]} & {offerings[1]}"
    elif niche_title:
        focus = niche_title
    title = f"{clean_name} | {focus} in {place}" if focus and place else f"{clean_name} | {place}" if place else clean_name
    if len(title) > 60:
        title = f"{clean_name} | {niche_title or focus} in {place}" if place else clean_name
    if len(title) > 60:
        title = f"{clean_name} | {place}" if place and len(clean_name) + len(place) + 3 <= 60 else clean_name[:60]

    noun = _NOUN_OVERRIDES.get(niche, niche)
    article = "an" if noun[:1].lower() in "aeiou" else "a"
    lead = (f"{clean_name} is {article} {noun} in {place}." if noun and place
            else f"{clean_name} in {place}." if place else f"{clean_name}.")
    pieces = [lead]
    if offerings:
        listed = offerings[0] if len(offerings) == 1 else ", ".join(offerings[:-1]) + f" and {offerings[-1]}"
        pieces.append(f" {listed}.")
    if audit.get("has_online_booking"):
        pieces.append(" Book online today.")
    elif prospect.get("phone"):
        pieces.append(f" Call {prospect['phone']} to book.")
    description = _fit(pieces, 158)

    url = audit.get("resolved_url") or prospect.get("website_url") or ""
    return {
        "url": re.sub(r"^https?://(www\.)?", "", url).rstrip("/"),
        "current_title": (audit.get("title") or "").strip() or None,
        "current_description": (audit.get("meta_description") or "").strip() or None,
        "suggested_title": title,
        "suggested_description": description,
    }
