"""The Website & AI Search emails: concrete market facts, zero fluff, no links on Email #1."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.services.chatgpt_check import trade_phrase
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
)
from pipeline.verticals import vertical_profile

PROMPT_VERSION = "seo-offer-v6"
AUDIT_ATTACHED = "audit_attached"
FREE_HOMEPAGE = "free_homepage"
WEBSITE_DRAFT = "website_draft"
COMPETITOR_GAP = "competitor_gap"
CHATGPT_PICK = "chatgpt_pick"
CHATGPT_PROFILE = "chatgpt_profile"
ATTACHES_AUDIT: set[str] = set()

_VOICE_BY_PROFILE: dict[str, dict[str, str]] = {
    "home_service": {
        "buyer": "homeowners",
        "outcome": "booked jobs",
        "mobile_friction": "tap-to-call, costing you calls",
    },
    "legal": {
        "buyer": "potential clients",
        "outcome": "signed cases",
        "mobile_friction": "request a consultation or call, costing you potential cases",
    },
    "real_estate": {
        "buyer": "buyers and sellers",
        "outcome": "listings and closings",
        "mobile_friction": "reach out or browse listings, costing you buyer and seller leads",
    },
    "medical_aesthetic": {
        "buyer": "patients",
        "outcome": "booked appointments",
        "mobile_friction": "book online or call, costing you patient appointments",
    },
    "dental": {
        "buyer": "patients",
        "outcome": "booked appointments",
        "mobile_friction": "book online or call, costing you new patient appointments",
    },
    "wellness_health": {
        "buyer": "patients",
        "outcome": "booked appointments",
        "mobile_friction": "book online or call, costing you patient appointments",
    },
    "auto": {
        "buyer": "drivers",
        "outcome": "booked repairs",
        "mobile_friction": "book or tap-to-call, costing you service appointments",
    },
    "generic_local_business": {
        "buyer": "locals",
        "outcome": "new clients",
        "mobile_friction": "reach out or tap-to-call, costing you client inquiries",
    },
}


def _voice(context: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    raw_vertical = context.get("vertical") or ((snapshot or {}).get("market_comparison") or {}).get("niche") or ""
    prof = vertical_profile(str(raw_vertical))
    return _VOICE_BY_PROFILE.get(prof, _VOICE_BY_PROFILE["generic_local_business"])


_SOCIAL_HOSTS = ("facebook.com", "fb.com", "instagram.com", "yelp.com", "linktr.ee", "linktree.com")


def _host(context: dict[str, Any]) -> str | None:
    url = context.get("resolved_url") or context.get("website_url") or ""
    if url and "://" not in url:
        url = f"https://{url}"
    host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    return host or None


def is_social_only(context: dict[str, Any]) -> bool:
    host = _host(context) or ""
    return any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS)


def display_name(name: str) -> str:
    """'Five Point Electric' -> 'Five Point', while 'Crazy Electric' stays whole."""
    short = short_name(name)
    if len(short.split()) >= 2:
        return short
    return re.split(r",|\s+a\s+(?=[A-Z])", name)[0].strip() or short


def _greeting(first_name: str | None, paragraphs: list[str]) -> str:
    return "\n\n".join([*([f"Hi {first_name},"] if first_name else []), *paragraphs])


def _rival_name(raw: Any) -> str:
    """'Mauzy Cooling, Heating, Plumbing, and Electrical, Inc.' -> 'Mauzy Cooling'."""
    name = clean_business_name(str(raw or "").split(",")[0])
    return "" if name == "your business" else name


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _top_service(context: dict[str, Any]) -> str | None:
    for raw in context.get("offering_titles") or []:
        title = " ".join(str(raw or "").split()).strip()
        if 3 <= len(title) <= 36 and not any(
            w in title.lower() for w in ("home", "about", "contact", "blog", "faq", "privacy")
        ):
            return title.lower()
    return None


def _review_count(context: dict[str, Any], snapshot: dict[str, Any] | None = None) -> int:
    biz = (snapshot or {}).get("business") if isinstance((snapshot or {}).get("business"), dict) else {}
    val = context.get("review_count") if context.get("review_count") is not None else biz.get("review_count")
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _hard_website_issue(context: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, str] | None:
    """One undeniable, high-conviction issue. Skips weak nitpicks."""
    findings = {f.get("signal"): f for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    signals = context.get("site_signals") or {}
    domain = _host(context) or "your site"
    short = display_name(clean_business_name(context.get("name")))
    city = (context.get("city") or "").strip()
    where = f" in {city}" if city else ""
    buyer = _voice(context, snapshot)["buyer"]

    if "broken_profile_link" in findings:
        return (
            f"Tried tapping the website button on {possessive(short)} Google Maps listing{where} earlier, "
            f"it goes to an error page, so anyone finding you on Maps hits a dead end.",
            "cleaner",
        )
    if "website_not_on_gbp" in findings:
        return (
            f"Pulled up {short} on Google Maps{where} earlier and noticed your website isn't linked on the listing, "
            f"so people checking you out there never reach {domain}.",
            "cleaner",
        )
    if "no_ssl" in findings:
        return (
            f"Pulled up {domain} earlier and Chrome threw a \"Not secure\" warning before the page even loaded, "
            f"most {buyer} back out right there.",
            "cleaner",
        )
    if signals.get("has_viewport") is False:
        return (
            f"Pulled up {domain} on mobile earlier and the page still loads desktop-sized, "
            f"so {buyer} have to pinch and zoom just to find your number.",
            "mobile-first",
        )
    speed = findings.get("psi_mobile_critical")
    if speed:
        lcp = (speed.get("data") or {}).get("lcp_ms")
        if isinstance(lcp, (int, float)) and lcp >= 5000:
            sec = round(lcp / 1000)
            return (
                f"Pulled up {domain} on mobile earlier and it took {sec} seconds before anything showed up, "
                f"most {buyer} bounce back to Google after 3.",
                "faster",
            )
    return None


def _chatgpt_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    """The two ChatGPT emails. Neither needs the website audit, links, or attachments."""
    name = clean_business_name(context.get("name"))
    short = display_name(name)
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    note = "" if first_name else "No contact name found, so there's no greeting."

    if angle == CHATGPT_PICK:
        evidence = context.get("chatgpt_evidence") or {}
        rivals = []
        for raw in evidence.get("competitors") or []:
            rival = _rival_name(raw)
            if rival and rival not in rivals:
                rivals.append(rival)
        rivals = rivals[:3]
        city = (context.get("city") or "").strip()
        if len(rivals) < 2 or evidence.get("prospect_named") is not False or not city:
            return None
        trade = trade_phrase(context.get("vertical"))
        reviews = _review_count(context, context.get("audit_snapshot"))
        domain = _host(context)
        site_ref = domain or "your site"
        if reviews >= 15:
            opener = (
                f"Saw {short} has {reviews:,} Google reviews in {city}, so I checked who ChatGPT "
                f"recommends for {trade} there. It named {_joined(rivals)}, {short} didn't come up."
            )
        else:
            opener = (
                f"Checked who ChatGPT recommends for {trade} in {city} today. "
                f"It named {_joined(rivals)}, {short} didn't come up."
            )
        paragraphs = [
            opener,
            f"Usually that's just 2 or 3 missing signals on {site_ref}. I noted what {rivals[0]} has "
            f"that you're missing, want me to send the 3 bullets over?",
        ]
        return {"subject": f"{short} on chatgpt".lower(), "body": _greeting(first_name, paragraphs),
                "angle": CHATGPT_PICK, "note": note}

    domain = _host(context)
    if not domain or is_social_only(context):
        return None
    paragraphs = [
        "OpenAI is rolling out business profiles in ChatGPT. A business claims its profile, "
        "verifies it, and can see how often ChatGPT mentions it.",
        f"Want me to check whether {short} has one yet and walk you through claiming it?",
    ]
    return {"subject": f"{short} chatgpt profile".lower(), "body": _greeting(first_name, paragraphs),
            "angle": CHATGPT_PROFILE, "note": note}


def _competitor_gap_email(context: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, str] | None:
    """Service-area & local competitor gap using real market_comparison leaders."""
    if is_social_only(context):
        return None
    domain = _host(context)
    if not domain:
        return None
    mc = snapshot.get("market_comparison") if isinstance(snapshot.get("market_comparison"), dict) else {}
    leaders = mc.get("leaders") or []
    name = clean_business_name(context.get("name"))
    short = display_name(name)
    my_reviews = _review_count(context, snapshot)

    leader_name = ""
    leader_reviews = 0
    for row in leaders:
        if not isinstance(row, dict):
            continue
        cand = _rival_name(row.get("name"))
        if not cand or cand.lower() == short.lower() or cand.lower() == name.lower():
            continue
        rev = int(row.get("review_count") or 0)
        if rev > my_reviews:
            leader_name = cand
            leader_reviews = rev
            break

    city = (context.get("city") or "").strip()
    if not leader_name or not city:
        return None

    findings = {f.get("signal") for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    if not (findings & {"no_service_city_pages", "no_service_pages"}):
        return None

    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"), signals.get("owner_name"))
    note = "" if first_name else "No contact name found, so there's no greeting."
    focus = _top_service(context) or trade_phrase(context.get("vertical"))
    review_clause = (
        f" ({leader_reviews:,} Google reviews vs. {possessive(short)} {my_reviews:,})"
        if my_reviews > 0 else f" ({leader_reviews:,} Google reviews)"
    )

    paragraphs = [
        f"Noticed {leader_name} is pulling a lot of the {city} searches for {focus} right now"
        f"{review_clause}, mostly because they have dedicated pages for each nearby area they serve "
        f"while {domain} lumps everything together.",
        f"I put together a quick 3-page outline showing which local {focus} pages would help {short} "
        f"capture those jobs. Want me to send it over?",
    ]
    return {
        "subject": f"{focus} in {city}".lower()[:42].strip(),
        "body": _greeting(first_name, paragraphs),
        "angle": COMPETITOR_GAP,
        "note": note,
    }


def write_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    if angle in (CHATGPT_PICK, CHATGPT_PROFILE):
        return _chatgpt_email(context, angle)
    snapshot = context.get("audit_snapshot")
    if not isinstance(snapshot, dict) or is_social_only(context):
        return None
    if angle == COMPETITOR_GAP:
        return _competitor_gap_email(context, snapshot)

    name = clean_business_name(context.get("name"))
    short = display_name(name)
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    demo_url = context.get("demo_url") or (snapshot.get("next_step") or {}).get("demo_url")
    note = "" if first_name else "No contact name found, so there's no greeting."
    service = _top_service(context)
    page_label = f"{service} page" if service else "homepage"

    if angle == FREE_HOMEPAGE and demo_url:
        city = (context.get("city") or "").strip()
        where = f" in {city}" if city else ""
        reviews = _review_count(context, snapshot)
        rep = f"has {reviews:,} solid reviews{where}" if reviews >= 15 else f"is well-reviewed{where}"
        paragraphs = [
            f"Saw {short} {rep}, so I mocked up a cleaner, mobile-first version of your {page_label} "
            f"to match your reputation.",
            "Mind if I shoot over the preview link? No strings attached, just wanted to share the build.",
        ]
        return {"subject": f"redesign for {short}".lower(), "body": _greeting(first_name, paragraphs),
                "angle": FREE_HOMEPAGE, "note": note}

    issue = _hard_website_issue(context, snapshot)
    if not issue:
        return None
    issue_line, quality = issue
    paragraphs = [issue_line]
    if signals.get("site_builder") == "toast":
        paragraphs.append("I moved a restaurant group's sites off Toast's builder onto their own fast "
                          "site and kept ordering on Toast.")
    paragraphs.append(f"I mocked up a {quality}, mobile-friendly version of {possessive(short)} {page_label} "
                      f"so you can see how it'd look. Want me to send the link over?")
    subj = f"{short}, {service}".lower() if service else f"{short} website".lower()
    return {"subject": subj[:42].strip(), "body": _greeting(first_name, paragraphs),
            "angle": WEBSITE_DRAFT, "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    """The one follow-up, same thread, no link."""
    name = clean_business_name(context.get("name"))
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    short = display_name(name)
    asset = {
        CHATGPT_PICK: "3 ChatGPT bullets",
        CHATGPT_PROFILE: "ChatGPT profile steps",
        COMPETITOR_GAP: "3 local page ideas",
    }.get(context.get("angle"), "homepage draft")
    return _greeting(
        first_name,
        [f"Quick bump: already have those {asset} for {short} pulled together. "
         f"Worth sending over, or not a priority right now?"],
    )
