"""The SEO, AEO/AI Search & Website Mockup emails, grounded in the lead's audit."""
from __future__ import annotations

from typing import Any

from app.services.outreach_audit_copy import (
    LEAD_PRIORITY,
    _email_phrase,
    _plural_niche,
    audit_email_paragraph,
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "seo-offer-v3"
AUDIT_ATTACHED = "audit_attached"
FREE_HOMEPAGE = "free_homepage"
AI_SEARCH = "ai_search"
ATTACHES_AUDIT: set[str] = set()


def _ask(short: str, city: str | None) -> str:
    where = f" in {city}" if city else ""
    return f"Open to me sending over the 1-page breakdown of what I'd fix first to capture those calls{where}?"


def _leader(snapshot: dict[str, Any], name: str) -> dict[str, Any] | None:
    comparison = snapshot.get("market_comparison") or {}
    mine = int((comparison.get("business") or {}).get("review_count") or 0)
    own = clean_business_name((comparison.get("business") or {}).get("name") or name).lower()
    for row in comparison.get("leaders") or []:
        rival = clean_business_name(row.get("name"))
        if rival.lower() != own and int(row.get("review_count") or 0) >= max(mine * 2, 20):
            return {"name": rival, "reviews": int(row["review_count"]), "mine": mine}
    return None


def _city(snapshot: dict[str, Any]) -> str | None:
    market = (snapshot.get("market_comparison") or {}).get("market")
    place = (market or "").split(",")[0].strip()
    return None if not place or place == "the area" else place


def _niche(snapshot: dict[str, Any]) -> str:
    return _plural_niche((snapshot.get("market_comparison") or {}).get("niche"))


def _singular_niche(snapshot: dict[str, Any]) -> str:
    niche = _niche(snapshot)
    if niche.endswith("ies"):
        return niche[:-3] + "y"
    if niche.endswith("s") and not niche.endswith("ss"):
        return niche[:-1]
    return niche


def _top_gap(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    gaps = (snapshot.get("page_gaps") or {}).get("gaps") or []
    top = gaps[0] if gaps else None
    return top if top and top.get("count") and top.get("label") else None


def _competitor_line(snapshot: dict[str, Any], name: str) -> tuple[str, str] | None:
    leader = _leader(snapshot, name)
    city = _city(snapshot)
    if not (leader and city):
        return None
    niche = _niche(snapshot)
    short = short_name(name)
    yours = (f"to your {leader['mine']:,}" if leader["mine"] else
             f"while {short} doesn't have any yet")
    line = (f"Ran a search check on {niche} in {city}. {leader['name']} is capturing most of the "
            f"top-3 map calls with {leader['reviews']:,} reviews {yours}")
    gap = _top_gap(snapshot)
    if gap:
        line += (f", and {gap['count']} other {niche} there have a dedicated {gap['label']} page "
                 f"that {possessive(short)} site is missing.")
    else:
        line += "."
    return line, f"calls going to {short_name(leader['name'])}".lower()


_HARD_GAPS = {"noindex_homepage", "website_not_on_gbp", "broken_profile_link", "no_website", "no_ssl",
              "no_reviews", "reviews_bottom_quartile"}


def _local_gap_line(snapshot: dict[str, Any], short: str, city: str | None) -> str | None:
    gap = _top_gap(snapshot)
    found = {f.get("signal") for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    if not (gap and city) or found & _HARD_GAPS:
        return None
    niche = _niche(snapshot)
    return (f"Checked {niche} in {city}. {gap['count']} other {niche} there have a dedicated "
            f"{gap['label']} page that {possessive(short)} site is missing, which is how they "
            "capture searches for that exact job.")


def _ai_search_paragraphs(snapshot: dict[str, Any], short: str, city: str | None) -> tuple[str, list[str]]:
    where = f" in {city}" if city else ""
    subject = f"chatgpt in {city}".lower() if city else f"ai search - {short}".lower()
    trade = _singular_niche(snapshot)
    leader = _leader(snapshot, short)
    rival_note = (f"{leader['name']} is consistently getting recommended first"
                  if leader else "a couple local competitors are consistently getting recommended first")
    found = {f.get("signal") for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    if "ai_crawlers_blocked" in found:
        reason = "your site is currently blocking AI search crawlers in robots.txt"
    elif "no_localbusiness_schema" in found:
        reason = "your site is missing the structured entity data AI models read to verify local businesses"
    else:
        reason = "your site isn't properly indexed for local AI entity answers yet"
    return subject, [
        f"Ran a scan on how ChatGPT and Apple Intelligence recommend {trade}s{where}. "
        f"When homeowners ask for a reliable {trade}, {rival_note}, while {short} isn't showing up because {reason}.",
        f"I put together a quick 1-page breakdown showing what AI search is outputting{where} and the 2 fixes needed to get {short} recommended.",
        "Mind if I send it over?",
    ]


def write_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    snapshot = context.get("audit_snapshot")
    if not isinstance(snapshot, dict):
        return None
    name = clean_business_name(context.get("name"))
    short = short_name(name)
    rendered = audit_email_paragraph(snapshot, name, with_demo=False)
    if rendered is None:
        return None
    finding, _ = rendered
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    city = _city(snapshot) or context.get("city")
    demo_url = context.get("demo_url") or (snapshot.get("next_step") or {}).get("demo_url")

    if angle == "leader_vs_you":
        angle = "competitor"
    elif angle == AUDIT_ATTACHED:
        angle = "local_gap"

    if angle == "competitor":
        rival = _competitor_line(snapshot, name)
        if rival is None:
            angle = "local_gap"
        else:
            finding, subject = rival
    elif angle == FREE_HOMEPAGE and not demo_url:
        angle = "local_gap"

    if angle == FREE_HOMEPAGE:
        subject = f"redesign for {short}".lower()
        where = f" in {city}" if city else ""
        paragraphs = [
            f"Looked through {possessive(short)} site on my phone today. You guys have solid reviews, "
            f"but the current layout makes it tough for mobile visitors to tap-to-call, which is costing you service requests{where}.",
            f"Rather than sending a boring SEO audit, I used our internal tool to build an interactive, "
            f"mobile-optimized mockup of what {possessive(short)} homepage should look like to capture those calls.",
            "Mind if I shoot over the preview link? No strings attached, just wanted to share the build.",
        ]
    elif angle == AI_SEARCH:
        subject, paragraphs = _ai_search_paragraphs(snapshot, short, city)
    elif angle == "competitor":
        paragraphs = [finding, _ask(short, city)]
    else:
        angle = "local_gap"
        subject = f"{city} service calls".lower() if city else f"quick question - {short}".lower()
        paragraphs = [_local_gap_line(snapshot, short, city) or finding, _ask(short, city)]

    return {
        "subject": subject[:70].lower(),
        "body": "\n\n".join([greeting, *paragraphs]),
        "angle": angle,
        "note": "No contact name found." if not first_name else "",
    }


_FIX_LINES = {
    "website_not_on_gbp": ("your Google Maps listing doesn't link to your website, so anyone who taps "
                           "it hits a dead end. Add it under Edit profile → Contact → Website. It takes "
                           "a minute."),
    "broken_profile_link": ("the website link on your Google Maps listing opens an error page, so anyone "
                            "who taps it hits a dead end. Fix it under Edit profile → Contact → Website. "
                            "It takes a minute."),
    "noindex_homepage": ("your homepage has a setting that tells Google not to show it in search. "
                         "Removing that one tag is the fastest win you have."),
    "no_ssl": ("your site shows a \"Not secure\" warning before it loads, and a lot of people back out "
               "right there. A free SSL certificate fixes it."),
    "no_click_to_call": ("your phone number isn't tappable on mobile, so people on their phones have to "
                         "copy it to call you. Making it a tap-to-call link takes five minutes."),
    "no_hours": ("your Google listing has no business hours, so Google is less likely to show you to "
                 "people searching right now. Add them under Edit profile → Hours."),
    "ai_crawlers_blocked": ("your site is blocking AI search tools like ChatGPT from reading it, so they "
                            "can't recommend you. It's one line in your robots.txt file."),
    "title_missing_location": ("your homepage title doesn't mention your town, and it's one of the first "
                               "things Google reads to decide where to show you."),
    "no_review_replies": ("none of your Google reviews have a reply. Replying, even briefly, is one of "
                          "the easier ways to move up on Maps."),
}
_FIX_ORDER = ("website_not_on_gbp", "broken_profile_link", "noindex_homepage", "no_ssl", "page_gap",
              "no_click_to_call", "no_hours", "ai_crawlers_blocked", "title_missing_location",
              "no_review_replies")


def fix_one(snapshot: dict[str, Any] | None, short: str, *, gap_already_named: bool = False) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    findings = [f for f in snapshot.get("findings") or [] if isinstance(f, dict) and f.get("signal")]
    found = {f["signal"] for f in findings}
    gap = _top_gap(snapshot)
    city = _city(snapshot)
    where = f" in {city}" if city else ""
    gap_line = (f"{gap['count']} other {_niche(snapshot)}{where} have a dedicated {gap['label']} page "
                f"and {possessive(short)} site doesn't. That page is how you show up when someone "
                "searches for that exact service.") if gap else None
    for key in _FIX_ORDER:
        if key == "page_gap":
            if gap_line and not gap_already_named:
                return gap_line
            continue
        if key in found:
            return _FIX_LINES[key]
    ordered = sorted(findings, key=lambda f: LEAD_PRIORITY.index(f["signal"])
                     if f["signal"] in LEAD_PRIORITY else 99)
    for item in ordered:
        if gap_already_named and item["signal"] in {"no_service_pages", "no_service_city_pages"}:
            continue
        phrase = _email_phrase(item)
        if phrase:
            return f"I'd start with {phrase}. It's a quick fix and it's costing you calls right now."
    return gap_line


def write_follow_up(context: dict[str, Any], step: int) -> str:
    name = clean_business_name(context.get("name"))
    short = short_name(name)
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    snapshot = context.get("audit_snapshot")
    city = (_city(snapshot) if isinstance(snapshot, dict) else None) or context.get("city")
    demo_url = context.get("demo_url") or ((snapshot.get("next_step") or {}).get("demo_url") if isinstance(snapshot, dict) else None)
    where = f" in {city}" if city else ""

    if step == 2:
        if context.get("angle") == FREE_HOMEPAGE and demo_url:
            paragraphs = [
                f"Figured I'd just drop the preview link so you can see it on your phone: {demo_url}",
                f"If you want to tweak anything or talk about getting it live to capture more calls{where}, just reply here.",
            ]
        else:
            fix = fix_one(snapshot, short, gap_already_named=context.get("angle") in {"competitor", "local_gap"})
            if fix:
                paragraphs = [
                    f"Quick one regardless: {fix}",
                    f"That's the fastest leak. Want me to send the rest of the {city or 'local'} breakdown?",
                ]
            else:
                paragraphs = [
                    f"Quick bump on this—did you want me to send over the 1-page breakdown for {short}, or is your schedule already completely full?",
                ]
    else:
        paragraphs = [
            "Last note from me—I know you probably get pitched every week by marketing companies promising rankings that never turn into actual jobs.",
            f"We work strictly month-to-month with zero upfront risk: if we don't bring in qualified local service calls{where}, you walk. "
            f"If you ever want to see the breakdown for {short}, just reply here. Otherwise, best of luck with the season.",
        ]
    return "\n\n".join([greeting, *paragraphs])
