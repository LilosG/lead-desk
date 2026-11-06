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
# Money gaps first: a broken path from Maps to the site, reviews, missing service
# pages. Owners don't buy speed scores, so PageSpeed only leads when nothing else does.
LEAD_PRIORITY = [
    "noindex_homepage", "website_not_on_gbp", "broken_profile_link", "no_website", "no_ssl",
    "no_reviews", "reviews_bottom_quartile", "no_service_pages", "ai_crawlers_blocked",
    "js_only_content", "reviews_below_median", "no_review_replies", "no_service_city_pages",
    "psi_mobile_critical", "psi_mobile_poor", "no_hours", "no_photos",
    "no_services_listed", "no_title", "title_missing_location", "no_click_to_call",
    "no_city_pages", "no_localbusiness_schema", "no_business_description", "no_gbp_link",
]

_LEGAL_SUFFIX = re.compile(
    r"[,\s]+(inc\.?|llc|l\.l\.c\.?|corp\.?|corporation|co\.|ltd\.?|pllc|pc|p\.c\.)$",
    re.IGNORECASE,
)


# How each finding reads in a sentence to the owner ("including ...").
EMAIL_PHRASES = {
    "no_website": "getting a website onto your Google listing",
    "website_not_on_gbp": "linking your website on your Google listing",
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
    "noindex_homepage": "a setting that's hiding your homepage from search engines",
    "ai_crawlers_blocked": "a setting that's blocking AI search tools from your site",
    "js_only_content": "page text that AI search tools can't read",
    "no_service_city_pages": "pages for your services in each town you serve",
    "thin_service_pages": "how little your service pages say",
    "title_missing_location": "getting your town into your homepage title",
    "no_click_to_call": "making your phone number tappable on mobile",
    "homepage_unclear": "saying what you do and where at the top of your homepage",
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


# Common US first names. A greeting uses a name only when it's certainly a name:
# "Hi Aaron," lands, and "Hi Jsmith," ends the conversation.
_FIRST_NAMES = frozenset("""
aaron adam adrian alan albert alex alexander alexis alicia alan allison alyssa amanda amber amy
ana andre andrea andrew andy angela anna anne anthony antonio april ashley austin barbara ben
benjamin beth betty bill billy blake bob bobby bonnie brad bradley brandon brenda brent brett
brian brittany bruce bryan caleb cameron carl carla carlos carol caroline carrie casey catherine
chad charles charlie chelsea cheryl chris christian christina christine christopher cindy claire
clark cody colin connor corey cory courtney craig crystal curtis cynthia dale damian dan dana
daniel danielle danny darren dave david dawn dean deborah debbie denise dennis derek diana diane
diego dominic don donald donna doug douglas drew dustin dylan eddie edward elena elizabeth ellen
emily emma eric erica erik erin ethan eugene evan evelyn frank fred gabriel gary gavin george
gerald gina glenn gloria grant greg gregory hannah harold harry heather hector helen henry holly
howard ian isaac ivan jack jackie jacob jake james jamie jan jane janet jason javier jay jean
jeff jeffrey jen jenna jennifer jenny jeremy jerry jesse jessica jesus jill jim jimmy joan joe
joel john johnny jon jonathan jordan jorge jose joseph josh joshua joy juan judy julia julie
justin karen kate katherine kathleen kathy katie keith kelly ken kenneth kevin kim kimberly
kristen kristin kurt kyle lance larry laura lauren lawrence leah lee leo leon linda lindsay lisa
logan lori louis lucas luis luke lynn marc marcus margaret maria marie marilyn mario mark marshall
martin marty mary mason matt matthew maria max megan melanie melissa michael michelle miguel mike
mitch mitchell molly monica morgan nancy natalie nathan neil nicholas nick nicole noah nolan norman
oscar owen pam pamela patricia patrick paul paula pedro peter phil philip phillip rachel ralph
randy ray raymond rebecca reed renee ricardo richard rick ricky rob robert roberto robin rod rodney
roger ron ronald rosa ross roy ruben russell ruth ryan sam samantha samuel sandra sara sarah scott
sean sergio seth shane shannon sharon shawn sheila shelly sherry sonia sophia spencer stacy stan
stephanie stephen steve steven stuart susan suzanne tammy tanya tara taylor ted teresa terry
theresa thomas tiffany tim timothy tina todd tom tommy tony tracy travis trevor troy tyler valerie
vanessa vicki victor victoria vincent virginia walter wayne wendy wesley william willie zach
zachary
""".split())
_GREETING_LINE = re.compile(r"^(?:Hi there|Hi|Hello),?[ \t]*$", re.MULTILINE)


def contact_first_name(
    email: str | None, business_name: str | None = None, site_owner: str | None = None,
) -> str | None:
    """A first name we can trust: the address, an owner-named business, or the site's owner."""
    local = (email or "").split("@")[0].lower()
    first = re.split(r"[._\-+]", local)[0]
    if first in _FIRST_NAMES:
        return first.capitalize()
    owner = re.match(r"^([A-Za-z]+)['’]s\b", (business_name or "").strip())
    if owner and owner.group(1).lower() in _FIRST_NAMES:
        return owner.group(1).capitalize()
    stated = (site_owner or "").split(" ")[0].lower()
    return stated.capitalize() if stated in _FIRST_NAMES else None


def personal_greeting(note: str, first_name: str | None) -> str:
    """Put the contact's name on the greeting line, when we know it."""
    if not first_name:
        return note
    return _GREETING_LINE.sub(f"Hi {first_name},", note, count=1)


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


_TRADE_SUFFIX = re.compile(
    r"\s+(electric(al)?|electricians?)(\s+(services?|contractors?|company|co\.?|solutions|group))*$",
    re.I,
)


def short_name(name: str) -> str:
    """'Five Point Electric' -> 'Five Point', for subjects that fit on a phone."""
    # 'Allied Electric a Buckles-Smith Company', 'Fuse Service HVAC, Electrical & Appliance Repair'
    head = re.split(r",|\s+a\s+(?=[A-Z])", name)[0].strip()
    return _TRADE_SUFFIX.sub("", head) or head or name


def team_greeting(first_name: str | None, name: str) -> str:
    return f"Hi {first_name}," if first_name else f"Hi {short_name(name)} team,"


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

    if signal == "website_not_on_gbp":
        return (
            f"{possessive(name)} Google listing doesn't link to your website, so people who "
            "find you on Google Maps can't get to it. The site itself is up; it just isn't "
            "on the listing.",
            f"{name} website on Google Maps",
        )
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


# Plural for "N other ___ in City". Unknown niches fall back to "<label> businesses".
_PLURALS = {
    "auto repair": "auto repair shops", "hvac": "HVAC companies", "roofing": "roofing companies",
    "landscaping": "landscaping companies", "real estate": "real estate agents",
    "pest control": "pest control companies", "party rental": "party rental companies",
}
_COUNT_NOUNS = ("spa", "dentist", "agent", "attorney", "lawyer", "electrician", "plumber",
                "chiropractor", "contractor", "clinic", "practice", "roofer", "painter",
                "cleaner", "orthodontist", "therapist", "realtor", "studio", "salon", "shop")


def _plural_niche(niche: str | None) -> str:
    label = (niche or "").strip()
    if not label or label == "comparable":
        return "businesses like yours"
    if label.lower() in _PLURALS:
        return _PLURALS[label.lower()]
    if label.lower().endswith(_COUNT_NOUNS):
        return label + "s"
    return f"{label} businesses"


def _bench_row(snapshot: dict[str, Any], metric: str) -> dict[str, Any] | None:
    for row in (snapshot.get("benchmarks") or {}).get("rows") or []:
        if row.get("metric") == metric:
            return row
    return None


def _bench_gap_sentence(signal: str, item: dict[str, Any], name: str,
                        snapshot: dict[str, Any]) -> str | None:
    """'The biggest gap ...' sentence for the lead finding, with the local typical."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    business = snapshot.get("business") if isinstance(snapshot.get("business"), dict) else {}
    comparison = snapshot.get("market_comparison") or {}
    if signal in {"psi_mobile_critical", "psi_mobile_poor"} and _num(data.get("psi_performance")):
        sentence = (f"The biggest gap is mobile speed: your homepage scored "
                    f"{_num(data['psi_performance'])}/100 on Google's speed test")
        try:
            if data.get("lcp_ms") and float(data["lcp_ms"]) >= 3000:
                sentence += f" and took about {float(data['lcp_ms']) / 1000:.0f} seconds to show up on a phone"
        except (TypeError, ValueError):
            pass
        row = _bench_row(snapshot, "Mobile speed score")
        if row and row.get("typical"):
            sentence += f". The typical one there scores {row['typical']}"
        return sentence + "."
    if signal in {"reviews_bottom_quartile", "reviews_below_median"}:
        reviews = _num(data.get("reviews", business.get("review_count")))
        median = _num(data.get("median", comparison.get("median_reviews")))
        if reviews and median:
            leaders = comparison.get("leaders") or []
            top = _num(leaders[0].get("review_count")) if leaders else None
            tail = f", and the most-reviewed has {top}" if top else ""
            return (f"The biggest gap is reviews: you have {reviews} on Google, the typical "
                    f"one has about {median}{tail}.")
    if signal == "no_reviews":
        return "The biggest gap is reviews: your Google listing doesn't have any yet."
    if signal == "no_website":
        return ("The biggest gap: your Google listing doesn't have a website on it, so people "
                "who find you on Maps have nowhere to look before deciding whether to call.")
    if signal == "website_not_on_gbp":
        return ("The biggest gap: your Google listing doesn't link to your website, so people "
                "who find you on Maps can't get to it. The site itself is up; it just isn't on the listing.")
    if signal == "broken_profile_link":
        return ("The biggest gap: the website link on your Google listing opens an error page, "
                "so anyone who taps \"Website\" on Maps hits a dead end. Your homepage itself loads fine.")
    if signal == "site_down":
        return "The biggest gap: when I opened your website from Google, it showed an error page."
    if signal == "no_ssl":
        return ("The biggest gap: your site loads without HTTPS, so browsers show visitors a "
                "\"Not secure\" warning first.")
    phrase = _email_phrase(item)
    return f"The clearest gap is {phrase}." if phrase else None


def _support_sentence(lead_signal: str, snapshot: dict[str, Any]) -> str | None:
    """One more concrete, local fact that isn't the lead."""
    gaps = (snapshot.get("page_gaps") or {}).get("gaps") or []
    if gaps and lead_signal not in {"no_service_pages"}:
        top = gaps[0]
        return f"{top['count']} of them also have their own {top['label']} page; your site doesn't."
    booking = _bench_row(snapshot, "Online booking")
    if booking and booking.get("verdict") == "behind":
        return f"{booking['typical'].replace(' offer it', '')} of them also take bookings online; your site doesn't."
    recent = _bench_row(snapshot, "Newest Google review")
    if (recent and recent.get("verdict") == "behind"
            and lead_signal not in {"reviews_bottom_quartile", "reviews_below_median", "no_reviews"}):
        return (f"Your newest Google review is from {recent['you']}; "
                f"for the typical one it's {recent['typical']}.")
    return None


_WEAK_LEADS = {"no_city_pages", "no_localbusiness_schema", "no_gbp_link",
               "no_business_description", "no_meta_description", "no_h1", "title_length"}


def _benchmark_email(snapshot: dict[str, Any], name: str,
                     ordered: list[dict[str, Any]]) -> tuple[str, str] | None:
    bench = snapshot.get("benchmarks") or {}
    comparison = snapshot.get("market_comparison") or {}
    city = _short_market(comparison.get("market"))
    n = bench.get("sample_size")
    if not (bench.get("rows") and city and n and n >= 5):
        return None
    gap = lead_signal = None
    for item in ordered:
        gap = _bench_gap_sentence(item["signal"], item, name, snapshot)
        if gap:
            lead_signal = item["signal"]
            break
    if not gap:
        return None
    # A low-impact lead ("location pages", "schema") is a weak opener. When
    # competitors have pages this site lacks, that's the more concrete gap.
    gaps = (snapshot.get("page_gaps") or {}).get("gaps") or []
    lead_item = next((i for i in ordered if i["signal"] == lead_signal), {})
    if gaps and (lead_signal in _WEAK_LEADS or lead_item.get("impact") == "low"):
        top = gaps[0]
        gap = (f"The clearest gap: {top['count']} of them have their own {top['label']} page, "
               "and your site doesn't.")
        lead_signal = "no_service_pages"
    parts = [f"Checked {name} against the other {_plural_niche(comparison.get('niche'))} in {city}.", gap]
    support = _support_sentence(lead_signal, snapshot)
    if support:
        parts.append(support)
    business = snapshot.get("business") if isinstance(snapshot.get("business"), dict) else {}
    try:
        rating, count = float(business.get("rating")), int(business.get("review_count") or 0)
        # One supporting fact is enough: under 100 words is what gets read.
        if rating >= 4.7 and count >= 10 and not support:
            parts.append(f"Your {rating:.1f}-star rating is strong, so this is about being found, "
                         "not your reputation.")
    except (TypeError, ValueError):
        pass
    paragraph = parts[0] + " " + parts[1]
    if len(parts) > 2:
        paragraph += "\n\n" + " ".join(parts[2:])
    return paragraph, f"How {name} compares in {city}"


def audit_email_paragraph(
    snapshot: dict[str, Any], business_name: str, *, with_demo: bool = True,
) -> tuple[str, str] | None:
    """(claim paragraph, subject) from an audit snapshot, or None if nothing usable.

    When the audit has a local benchmark, the email leads with it ("I compared
    you with 29 other med spas in Scottsdale. The biggest gap is ...") plus one
    more local fact. Otherwise it leads with the single strongest finding.
    """
    findings = [f for f in (snapshot.get("findings") or []) if isinstance(f, dict) and f.get("signal")]
    if not findings:
        return None
    name = clean_business_name(business_name)
    ordered_for_bench = sorted(
        findings,
        key=lambda f: LEAD_PRIORITY.index(f["signal"]) if f["signal"] in LEAD_PRIORITY else 99,
    )
    demo_url = (snapshot.get("next_step") or {}).get("demo_url") if with_demo else None
    demo_line = (
        f"\n\nI also mocked up what a new homepage could look like for you: {demo_url}"
        if demo_url else ""
    )
    benchmarked = _benchmark_email(snapshot, name, ordered_for_bench)
    if benchmarked:
        paragraph, subject = benchmarked
        return paragraph + demo_line, subject[:70]

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

    return opening + demo_line, subject[:60]
