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
number when there is one; name the business once, then talk to the owner
("your listing"); say how many other items the attached audit covers and name
at most two. No links. The attachment line comes from the frame.
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


# How each finding reads in a sentence to the owner ("including ...").
EMAIL_PHRASES = {
    "no_website": "getting a website onto your Google listing",
    "broken_profile_link": "the broken website link on your Google listing",
    "site_down": "your website not loading",
    "psi_mobile_critical": "how slowly your site loads on phones",
    "psi_mobile_poor": "how slowly your site loads on phones",
    "no_ssl": "the \"Not secure\" warning on your site",
    "no_reviews": "getting your first Google reviews in",
    "reviews_bottom_quartile": "your number of Google reviews",
    "reviews_below_median": "your number of Google reviews",
    "no_review_replies": "replying to your reviews",
    "few_review_replies": "replying to your reviews",
    "no_hours": "your business hours on Google",
    "no_photos": "photos on your Google listing",
    "few_photos": "photos on your Google listing",
    "no_services_listed": "the services list on your Google listing",
    "no_business_description": "the description on your Google listing",
    "category_generic": "your main category on Google",
    "no_title": "your homepage's search title",
    "title_length": "your homepage's search title",
    "no_meta_description": "the description Google shows under your homepage",
    "no_h1": "your homepage's main heading",
    "thin_content": "how little text is on your homepage",
    "no_contact_form": "an online way to contact or book you",
    "no_localbusiness_schema": "some behind-the-scenes setup Google uses to read your site",
    "no_gbp_link": "a reviews link on your website",
    "nap_mismatch": "the phone number on your site vs. Google",
    "no_service_pages": "dedicated service pages",
    "no_city_pages": "pages for the areas you serve",
}

# For these, the report's own niche wording ("treatment pages") is better.
_PREFER_REPORT_PHRASE = {"no_service_pages", "no_city_pages"}


def _email_phrase(item: dict[str, Any]) -> str:
    signal = item.get("signal")
    if signal in _PREFER_REPORT_PHRASE and (item.get("phrase") or "").strip():
        phrase = item["phrase"].strip()
        return phrase if phrase.startswith(("dedicated", "a ", "your")) else f"dedicated {phrase}"
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
    """(opening paragraph, subject) for the lead finding, or None.

    Written to the owner ("your listing"), naming the business once at most.
    """
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    business = snapshot.get("business") if isinstance(snapshot.get("business"), dict) else {}
    comparison = snapshot.get("market_comparison") or {}

    if signal == "broken_profile_link":
        return (
            f"The website link on {possessive(name)} Google listing opens an error page right "
            "now, so anyone who taps \"Website\" from Google Maps hits a dead end. The homepage "
            "itself loads fine; it's just the link on the listing.",
            f"{name} website link on Google",
        )
    if signal == "no_website":
        return (
            f"{possessive(name)} Google listing doesn't have a website on it, so people who find "
            "you on Google Maps have nowhere to look before deciding whether to call.",
            f"{name} on Google Maps",
        )
    if signal in {"psi_mobile_critical", "psi_mobile_poor"}:
        score = _num(data.get("psi_performance"))
        lcp = data.get("lcp_ms")
        if score:
            wait = ""
            try:
                if lcp and float(lcp) >= 3000:
                    wait = (f" On a phone, the main content took about {float(lcp) / 1000:.0f} "
                            "seconds to show up, and most people searching locally won't wait that long.")
            except (TypeError, ValueError):
                wait = ""
            return (
                f"I ran {possessive(name)} homepage through Google's mobile speed test and it "
                f"scored {score} out of 100.{wait or ' Most people searching locally are on their phone, so that costs calls.'}",
                f"{name} website on phones",
            )
        return (
            f"{possessive(name)} homepage scored poorly on Google's mobile speed test, and most "
            "people searching locally are on their phone.",
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
            f"When I opened {possessive(name)} website from the Google listing, it showed an "
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

    remaining = len({f["signal"] for f in findings}) - 1
    if lead_signal in review_signals:
        remaining -= sum(1 for f in findings if f["signal"] in review_signals and f["signal"] != lead_signal)
    if others and remaining >= 2:
        named = f"{others[0]} and {others[1]}" if len(others) == 2 else others[0]
        opening += f"\n\nI found {remaining} other things worth fixing too, including {named}."
    elif others:
        opening += f"\n\nThere's one other thing worth fixing too: {others[0]}."
    return opening, subject[:60]
