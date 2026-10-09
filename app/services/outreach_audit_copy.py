"""First-touch email copy grounded in a generated audit report.

What this fixes, from the real drafts reviewed on 2026-10-08:
  * every email opened with the same "Google shows X at 5.0 stars across N
    reviews, but the audit found several areas..." sentence;
  * findings were jargon ("structured business data", "the website-to-Google
    profile connection") instead of something an owner recognises;
  * "several areas" was said even when there was one finding;
  * keyword-stuffed Google names ("Waterfront Plumbing | 24/7 Emergency
    Plumbers in Vista") went into subjects and bodies verbatim.

Rules: lead with ONE concrete, verifiable finding in plain English, with its
number when there is one; mention at most two more by name; no links, no
attachment claims (the report is offered, then sent on reply).
"""
from __future__ import annotations

import re
from typing import Any

# Order in which a finding makes the strongest opening line.
LEAD_PRIORITY = [
    "broken_profile_link", "no_website", "psi_mobile_critical", "no_reviews",
    "reviews_bottom_quartile", "no_ssl", "psi_mobile_poor", "reviews_below_median",
    "no_review_replies", "no_service_pages", "no_hours", "no_photos",
    "no_services_listed", "no_title", "no_city_pages", "no_localbusiness_schema",
    "no_business_description", "no_gbp_link",
]

_LEGAL_SUFFIX = re.compile(
    r"[,\s]+(inc\.?|llc|l\.l\.c\.?|corp\.?|corporation|co\.|ltd\.?|pllc|pc|p\.c\.)$",
    re.IGNORECASE,
)


# How each finding reads in a sentence to an owner ("I also noted ...").
EMAIL_PHRASES = {
    "no_website": "having no website on the listing",
    "broken_profile_link": "the broken website link on Google",
    "site_down": "the website not loading",
    "psi_mobile_critical": "how slowly the site loads on phones",
    "psi_mobile_poor": "how slowly the site loads on phones",
    "no_ssl": "the \"Not secure\" warning on the site",
    "no_reviews": "getting the first Google reviews in",
    "reviews_bottom_quartile": "the number of Google reviews",
    "reviews_below_median": "the number of Google reviews",
    "no_review_replies": "replying to reviews",
    "no_hours": "the business hours on Google",
    "no_photos": "photos on the Google listing",
    "no_services_listed": "the services list on Google",
    "no_business_description": "the description on the Google listing",
    "no_title": "the headline Google shows for the homepage",
    "no_localbusiness_schema": "some behind-the-scenes setup Google uses to read the site",
    "no_gbp_link": "a reviews link on the website",
    "no_service_pages": "dedicated service pages",
    "no_city_pages": "pages for the areas you serve",
}

# For these, the report's own niche wording ("treatment pages") is better.
_PREFER_REPORT_PHRASE = {"no_service_pages", "no_city_pages"}


def _email_phrase(item: dict[str, Any]) -> str:
    signal = item.get("signal")
    if signal in _PREFER_REPORT_PHRASE and (item.get("phrase") or "").strip():
        return item["phrase"].strip()
    if signal in EMAIL_PHRASES:
        return EMAIL_PHRASES[signal]
    return (item.get("phrase") or "").strip()


def _short_market(market: str | None) -> str | None:
    if not market or market == "the area":
        return None
    return market.split(",")[0].strip() or None


def _niche_noun(niche: str | None) -> str:
    niche = (niche or "").strip()
    if not niche or niche == "comparable":
        return "business like yours"
    return niche


def clean_business_name(name: str | None) -> str:
    """'Waterfront Plumbing | 24/7 Emergency Plumbers in Vista' -> 'Waterfront Plumbing'."""
    text = " ".join(str(name or "").split())
    if not text:
        return "your business"
    text = re.split(r"\s+[|•·]\s+", text)[0]
    # "Ascend Plumbing - San Diego CA" / "Skin Laundry - Scottsdale Quarter"
    parts = re.split(r"\s+[-–—]\s+", text)
    if len(parts) > 1 and len(parts[0].split()) >= 2:
        text = parts[0]
    previous = None
    while previous != text:
        previous = text
        text = _LEGAL_SUFFIX.sub("", text).strip(" ,")
    return text or "your business"


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _finding(snapshot: dict[str, Any], signal: str) -> dict[str, Any] | None:
    for item in snapshot.get("findings") or []:
        if isinstance(item, dict) and item.get("signal") == signal:
            return item
    return None


def _num(value: Any) -> str | None:
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return None


def _lead_sentence(signal: str, item: dict[str, Any], name: str,
                   snapshot: dict[str, Any]) -> tuple[str, str] | None:
    """(opening paragraph, subject) for the lead finding, or None."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    business = snapshot.get("business") if isinstance(snapshot.get("business"), dict) else {}
    comparison = snapshot.get("market_comparison") or {}
    phrase = item.get("phrase") or ""

    if signal == "broken_profile_link":
        return (
            f"The website link on {possessive(name)} Google listing opens an error page "
            "right now, so anyone who taps \"Website\" from Google Maps hits a dead end. "
            "The homepage itself loads fine; it's just the link on the listing.",
            f"{name} website link on Google",
        )
    if signal == "no_website":
        return (
            f"{possessive(name)} Google listing doesn't have a website on it, so people who "
            "find you on Google Maps have nowhere to look before deciding whether to call.",
            f"{name} on Google Maps",
        )
    if signal in {"psi_mobile_critical", "psi_mobile_poor"}:
        score = _num(data.get("psi_performance"))
        lcp = data.get("lcp_ms")
        if score:
            secs = (
                f"; the main content took about {float(lcp) / 1000:.0f} seconds to appear on a phone"
                if lcp else ""
            )
            return (
                f"I ran {possessive(name)} homepage through Google's mobile speed test and it "
                f"scored {score} out of 100{secs}. Most people looking for a local business "
                "are on their phone, and a lot of them won't wait that long.",
                f"{name} website on phones",
            )
        return (
            f"{possessive(name)} homepage scored poorly on Google's mobile speed test, and most "
            "people looking for a local business are on their phone.",
            f"{name} website on phones",
        )
    if signal in {"reviews_bottom_quartile", "reviews_below_median", "no_reviews"}:
        if signal == "no_reviews":
            return (
                f"{possessive(name)} Google listing doesn't have any reviews yet. When people "
                "compare options on Google Maps, reviews are usually the first thing they look at.",
                f"{name} Google reviews",
            )
        reviews = _num(data.get("reviews", business.get("review_count")))
        median = _num(data.get("median", comparison.get("median_reviews")))
        niche = _niche_noun(comparison.get("niche") or data.get("niche"))
        city = _short_market(comparison.get("market") or data.get("market"))
        where = f" in {city}" if city else " nearby"
        rating = business.get("rating")
        count = int(str(reviews).replace(",", "")) if reviews else 0
        if reviews and median:
            praise = ""
            try:
                if rating is not None and float(rating) >= 4.7 and count >= 10:
                    praise = f" Your {float(rating):.1f}-star average is great, so it's really about volume."
            except (TypeError, ValueError):
                praise = ""
            return (
                f"{name} has {reviews} Google review{'s' if count != 1 else ''}; the typical "
                f"{niche}{where} has about {median}. On Google Maps, that's one of the first "
                f"things people compare.{praise}",
                f"{name} Google reviews",
            )
    if signal == "site_down":
        return (
            f"When I opened {possessive(name)} website from its Google listing, it showed an "
            "error page instead of the site.",
            f"{name} website",
        )
    if signal == "no_ssl":
        return (
            f"{possessive(name)} website loads without HTTPS, so browsers show visitors a "
            "\"Not secure\" warning before they see anything else.",
            f"{name} website security",
        )
    phrase = _email_phrase(item)
    if phrase:
        return (
            f"I looked over {possessive(name)} Google listing and website, and the clearest "
            f"thing to fix is {phrase}.",
            f"{name} website",
        )
    return None


def audit_email_paragraph(snapshot: dict[str, Any], business_name: str) -> tuple[str, str] | None:
    """(claim paragraph, subject) from an audit snapshot, or None if nothing usable."""
    findings = [f for f in (snapshot.get("findings") or []) if isinstance(f, dict) and f.get("signal")]
    if not findings:
        return None
    name = clean_business_name(business_name)

    ordered = sorted(
        findings,
        key=lambda f: LEAD_PRIORITY.index(f["signal"]) if f["signal"] in LEAD_PRIORITY else 99,
    )
    lead = None
    for item in ordered:
        lead = _lead_sentence(item["signal"], item, name, snapshot)
        if lead:
            lead_signal = item["signal"]
            break
    if not lead:
        return None
    opening, subject = lead

    review_signals = {"reviews_bottom_quartile", "reviews_below_median", "no_reviews"}
    others: list[str] = []
    for item in ordered:
        if item["signal"] == lead_signal:
            continue
        if lead_signal in review_signals and item["signal"] in review_signals:
            continue
        phrase = _email_phrase(item)
        if phrase and phrase not in others and phrase not in opening:
            others.append(phrase)
        if len(others) == 2:
            break

    if len(others) == 2:
        opening += f"\n\nThere are a couple of other things worth fixing too, including {others[0]} and {others[1]}."
    elif len(others) == 1:
        opening += f"\n\nThere's one other thing worth fixing too: {others[0]}."
    return opening, subject[:60]
