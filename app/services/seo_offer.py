"""The Website emails: a real detail from their site, 1-2 problems they can
check on their own phone, and an offer of a free draft. No links or attachments.

Problems come only from verified data: the audit's findings (Google listing
link, SSL, mobile speed, tappable phone number) and the site scan (viewport).
Leads whose listing points at a social profile get no website email.
"""
from __future__ import annotations

from typing import Any

import re
from urllib.parse import urlparse

from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
)
from app.services.chatgpt_check import trade_phrase
from pipeline.verticals import vertical_profile

PROMPT_VERSION = "seo-offer-v5"
AUDIT_ATTACHED = "audit_attached"
FREE_HOMEPAGE = "free_homepage"
WEBSITE_DRAFT = "website_draft"
CHATGPT_PICK = "chatgpt_pick"
CHATGPT_PROFILE = "chatgpt_profile"
ATTACHES_AUDIT: set[str] = set()

_VOICE_BY_PROFILE: dict[str, dict[str, str]] = {
    "home_service": {
        "subject_leads": "service calls",
        "buyer": "homeowners",
        "inquiries": "service calls",
        "map_leads": "top-3 map calls",
        "outcome": "booked jobs",
        "search_intent": "that exact job",
        "mobile_friction": "tap-to-call, costing you calls",
    },
    "legal": {
        "subject_leads": "case inquiries",
        "buyer": "potential clients",
        "inquiries": "case inquiries",
        "map_leads": "top-3 Google Maps case inquiries",
        "outcome": "signed cases",
        "search_intent": "that exact practice area",
        "mobile_friction": "request a consultation or call, costing you potential cases",
    },
    "real_estate": {
        "subject_leads": "client leads",
        "buyer": "buyers and sellers",
        "inquiries": "client inquiries",
        "map_leads": "top-3 Google Maps client leads",
        "outcome": "listings and closings",
        "search_intent": "homes and agents in their area",
        "mobile_friction": "reach out or browse listings, costing you buyer and seller leads",
    },
    "medical_aesthetic": {
        "subject_leads": "patient bookings",
        "buyer": "patients",
        "inquiries": "patient inquiries",
        "map_leads": "top-3 Google Maps patient bookings",
        "outcome": "booked appointments",
        "search_intent": "that exact treatment",
        "mobile_friction": "book online or call, costing you patient appointments",
    },
    "dental": {
        "subject_leads": "new patient calls",
        "buyer": "patients",
        "inquiries": "patient inquiries",
        "map_leads": "top-3 Google Maps patient bookings",
        "outcome": "booked appointments",
        "search_intent": "that exact procedure",
        "mobile_friction": "book online or call, costing you new patient appointments",
    },
    "wellness_health": {
        "subject_leads": "patient bookings",
        "buyer": "patients",
        "inquiries": "patient inquiries",
        "map_leads": "top-3 Google Maps patient bookings",
        "outcome": "booked appointments",
        "search_intent": "that exact service",
        "mobile_friction": "book online or call, costing you patient appointments",
    },
    "auto": {
        "subject_leads": "repair bookings",
        "buyer": "drivers",
        "inquiries": "service bookings",
        "map_leads": "top-3 Google Maps repair calls",
        "outcome": "booked repairs",
        "search_intent": "that exact repair",
        "mobile_friction": "book or tap-to-call, costing you service appointments",
    },
    "generic_local_business": {
        "subject_leads": "client inquiries",
        "buyer": "locals",
        "inquiries": "client inquiries",
        "map_leads": "top-3 Google Maps leads",
        "outcome": "new clients",
        "search_intent": "that exact service",
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
    """'Five Point Electric' -> 'Five Point', but 'Crazy Electric' stays whole rather than 'Crazy'."""
    short = short_name(name)
    if len(short.split()) >= 2:
        return short
    return re.split(r",|\s+a\s+(?=[A-Z])", name)[0].strip() or short


def _greeting(first_name: str | None, paragraphs: list[str]) -> str:
    return "\n\n".join([*([f"Hi {first_name},"] if first_name else []), *paragraphs])


def _opener(domain: str, hook: dict[str, Any] | None) -> str:
    kind = (hook or {}).get("kind")
    value = (hook or {}).get("value")
    detail = {
        "since": f"saw you've been around since {value}",
        "years": f"saw {value}+ years in business",
        "experience": f"saw {value}+ years of experience",
        "license": f"saw you're a licensed {value} contractor",
        "response": f"saw you offer {value}-hour response",
        "family": "saw you're family-owned",
    }.get(kind) if value else None
    if detail:
        return f"Was on {domain} and {detail}. That's worth leading with."
    return f"Looked through {domain} on my phone today."


def _problems(context: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Verified, phone-checkable problems, most serious first."""
    findings = {f.get("signal"): f for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    signals = context.get("site_signals") or {}
    lines: list[str] = []
    if "broken_profile_link" in findings:
        lines.append("The website link on your Google Maps listing opens an error page, so people "
                     "who find you on Maps hit a dead end.")
    elif "website_not_on_gbp" in findings:
        lines.append("Your Google Maps listing doesn't link to your website, so people who find you "
                     "on Maps never see it.")
    if "no_ssl" in findings:
        lines.append("Browsers show a \"Not secure\" warning before your site loads, and a lot of "
                     "people back out right there.")
    speed = findings.get("psi_mobile_critical") or findings.get("psi_mobile_poor")
    if speed:
        lcp = (speed.get("data") or {}).get("lcp_ms")
        if isinstance(lcp, (int, float)) and lcp >= 3000:
            lines.append(f"On a weaker phone signal it takes about {round(lcp / 1000)} seconds before "
                         "anything shows up, and most people are gone by then.")
        else:
            lines.append("It's slow to load on a phone, and most people don't wait.")
    if signals.get("has_viewport") is False:
        lines.append("On a phone the page shows up desktop-sized, so people have to pinch and zoom "
                     "to read it.")
    if "no_click_to_call" in findings or signals.get("has_click_to_call") is False:
        lines.append("Your phone number isn't tappable on mobile, so people have to copy it to call you.")
    return lines


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


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
        rivals = (evidence.get("competitors") or [])[:3]
        city = context.get("city")
        if len(rivals) < 2 or evidence.get("prospect_named") is not False or not city:
            return None
        paragraphs = [
            f"I asked ChatGPT for the best {trade_phrase(context.get('vertical'))} in {city}. "
            f"It named {_joined(rivals)}. {short} didn't come up.",
            "People are starting to ask it who to call.",
            f"Want me to send over a breakdown of what those businesses are doing that {short} isn't?",
        ]
        return {"subject": f"{short} on ChatGPT".lower(), "body": _greeting(first_name, paragraphs),
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


def write_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    if angle in (CHATGPT_PICK, CHATGPT_PROFILE):
        return _chatgpt_email(context, angle)
    snapshot = context.get("audit_snapshot")
    if not isinstance(snapshot, dict) or is_social_only(context):
        return None
    name = clean_business_name(context.get("name"))
    short = short_name(name)
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    demo_url = context.get("demo_url") or (snapshot.get("next_step") or {}).get("demo_url")
    note = "" if first_name else "No contact name found, so there's no greeting."

    if angle == FREE_HOMEPAGE and demo_url:
        city = context.get("city")
        where = f" in {city}" if city else ""
        voice = _voice(context, snapshot)
        paragraphs = [
            f"Looked through {possessive(short)} site on my phone today. You guys have solid reviews, "
            f"but the current layout makes it tough for mobile visitors to {voice['mobile_friction']}{where}.",
            f"Rather than sending a boring SEO audit, I used our internal tool to build an interactive, "
            f"mobile-optimized mockup of what {possessive(short)} homepage should look like.",
            "Mind if I shoot over the preview link? No strings attached, just wanted to share the build.",
        ]
        return {"subject": f"redesign for {short}".lower(), "body": _greeting(first_name, paragraphs),
                "angle": FREE_HOMEPAGE, "note": note}

    domain = _host(context)
    problems = _problems(context, snapshot)
    if not domain or not problems:
        return None
    paragraphs = [_opener(domain, signals.get("site_hook"))]
    lead = "A couple of things are probably costing you calls, though." if len(problems) > 1 else \
        "One thing is probably costing you calls, though."
    paragraphs.append(" ".join([lead, *problems[:2]]))
    if signals.get("site_builder") == "toast":
        paragraphs.append("I moved a restaurant group's sites off Toast's builder onto their own fast "
                          "site and kept ordering on Toast.")
    paragraphs.append("I put together a draft of a faster, mobile-friendly version. Want me to send it over?")
    if not signals.get("site_hook"):
        note = (note + " No homepage detail found, so it opens on the site itself.").strip()
    return {"subject": f"{display_name(name)} website".lower(), "body": _greeting(first_name, paragraphs),
            "angle": WEBSITE_DRAFT, "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    """The one follow-up, same thread, no link."""
    name = clean_business_name(context.get("name"))
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    short = display_name(name)
    ask = {
        CHATGPT_PICK: f"Want me to send over the breakdown of what those businesses are doing on ChatGPT that {short} isn't?",
        CHATGPT_PROFILE: f"Want me to walk you through claiming {possessive(short)} ChatGPT profile?",
    }.get(context.get("angle"),
          f"Want me to send over that mobile-friendly homepage draft for {short} so you can take a look?")
    return _greeting(first_name, [f"Quick bump on this. {ask}"])
