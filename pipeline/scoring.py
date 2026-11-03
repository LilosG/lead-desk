"""
Scoring — turn raw signals into a ranked, evidence-backed opportunity score.

Design principles:

1. Score = OPPORTUNITY, not quality. High score means "visibly underserved and
   we can prove it," not "good business."

2. Relative, not absolute. 23 reviews is weak for a Carlsbad electrician and
   strong for a Julian septic contractor. Every volume signal is scored against
   the per-vertical, per-geo median from THIS run. Fixed thresholds are what
   make generic lead lists useless.

3. Every point carries evidence. Each signal emits a pitch-ready sentence and
   the raw observed value. That payload feeds both the cold email and the free
   40-signal GBP audit PDF that Lilos already sells as its lead magnet.

4. Reachability is a MULTIPLIER, not an addend. If reachability is just another
   weighted component, a perfectly-optimized business with a good contact page
   collects "opportunity" points for being easy to reach. It determines whether
   you can act on an opportunity, not whether one exists.

5. A good lead needs BOTH fit and opportunity. Fit asks "is this a real, working
   business that could buy?"; opportunity asks "is there a gap we can prove?".
   They multiply (geometric mean), so a flawless business and a dead listing both
   score low, and an established business with a weak website scores high:

       opportunity = 0.7 * worse axis + 0.3 * better axis, less a small noise floor
       total       = sqrt(fit * opportunity) * reachability_multiplier

   Model v2 averaged the two gap axes and ignored fit, which graded an active
   85-review business with a weak site Tier D and a dormant 2-review listing
   above it.

6. Qualification is a verdict, not a tier. Tier ranks the list; `qualification`
   says what to do with a lead and why. Nothing is deleted: a lead that isn't
   qualified stays in the list with the reason.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import config as C
import site_signals as SS
import verticals as V

# Raw points at which each axis reads "clearly underserved" (scores cap at 100).
# Add or reweight a signal and these may need re-tuning: see pipeline/test_scoring.py.
GBP_MAX_POINTS = C.GBP_SATURATION_POINTS
WEBSITE_MAX_POINTS = C.WEBSITE_SATURATION_POINTS

# The two dominant website outcomes bypass the itemized path and map straight
# onto the top of the axis, because "no site" and "site is down" are strictly
# bigger opportunities than any accumulation of on-page nitpicks.
NO_WEBSITE_AXIS_SCORE = 100
SITE_DOWN_AXIS_SCORE = 85
BROKEN_LINK_AXIS_SCORE = 75
UNLISTED_SITE_POINTS = 20  # site exists but isn't linked on the Google profile


def _normalize(points: int, axis_max: int) -> int:
    return int(round(min(points, axis_max) / axis_max * 100))


@dataclass
class Evidence:
    category: str
    signal: str
    severity: str
    points: int
    finding: str
    observed: dict = field(default_factory=dict)


@dataclass
class Baseline:
    vertical: str
    geo_label: str
    sample_size: int
    median_reviews: float
    p25_reviews: float
    p75_reviews: float
    median_rating: float
    pct_with_website: float
    median_psi_perf: float | None = None


ALL_MARKETS = "All markets"


def baseline_key(vertical: str | None, market: str | None) -> str:
    return f"{vertical or 'unknown'}|{market or ALL_MARKETS}"


def market_display(market: str | None) -> str:
    """'Austin, TX, USA' -> 'Austin, TX'."""
    if not market or market == ALL_MARKETS:
        return "the area"
    parts = [p.strip() for p in market.split(",") if p.strip()]
    if parts and parts[-1].upper() in {"USA", "US", "UNITED STATES"}:
        parts = parts[:-1]
    return ", ".join(parts[:2]) or market


def _baseline(vertical: str, label: str, rows: list) -> Baseline:
    reviews = sorted([r.get("review_count") or 0 for r in rows])
    ratings = [float(r["rating"]) for r in rows if r.get("rating")]
    with_site = sum(1 for r in rows if r.get("website_url"))
    n = len(rows)

    def pct(vals, p):
        if not vals:
            return 0.0
        k = max(0, min(len(vals) - 1, int(round((p / 100) * (len(vals) - 1)))))
        return float(vals[k])

    return Baseline(
        vertical=vertical,
        geo_label=label,
        sample_size=n,
        median_reviews=float(statistics.median(reviews)) if reviews else 0.0,
        p25_reviews=pct(reviews, 25),
        p75_reviews=pct(reviews, 75),
        median_rating=float(statistics.median(ratings)) if ratings else 0.0,
        pct_with_website=(with_site / n * 100) if n else 0.0,
    )


def compute_baselines(businesses: list, geo_label: str | None = None) -> dict:
    """Medians per niche AND per searched market, plus a niche-wide fallback.

    A Phoenix dentist is compared with Phoenix dentists, not with every dentist
    the run touched. Markets too small to trust fall back to the niche-wide
    numbers for the run (see baseline_for).
    """
    by_vertical: dict = {}
    by_market: dict = {}
    for b in businesses:
        v = b.get("vertical") or "unknown"
        by_vertical.setdefault(v, []).append(b)
        by_market.setdefault((v, b.get("market") or geo_label or ALL_MARKETS), []).append(b)

    out: dict = {}
    for vertical, rows in by_vertical.items():
        out[baseline_key(vertical, None)] = _baseline(vertical, ALL_MARKETS, rows)
    for (vertical, market), rows in by_market.items():
        if market == ALL_MARKETS:
            continue
        out[baseline_key(vertical, market)] = _baseline(vertical, market, rows)
    return out


def baseline_for(baselines: dict, vertical: str | None, market: str | None) -> Baseline | None:
    local = baselines.get(baseline_key(vertical, market)) if market else None
    if local is not None and local.sample_size >= C.MIN_MARKET_BASELINE_SAMPLE:
        return local
    return baselines.get(baseline_key(vertical, None)) or local


# ---------------------------------------------------------------------------
# GBP gaps — 40% of score
# ---------------------------------------------------------------------------
def score_gbp(b: dict, base: Baseline) -> tuple[int, list]:
    ev: list = []
    pts = 0

    reviews = b.get("review_count") or 0
    rating = float(b.get("rating") or 0)
    name = b.get("name") or "This business"

    # Review volume vs local peers
    where = market_display(base.geo_label)
    niche = V.vertical_label(base.vertical) if base.vertical != "unknown" else "local"
    peer_obs = {"median": base.median_reviews, "market": where,
                "niche": niche, "sample_size": base.sample_size}
    if reviews == 0:
        pts += 22
        ev.append(Evidence("gbp", "no_reviews", "critical", 22,
            f"{name} has zero Google reviews. Comparable {niche} businesses in {where} "
            f"have a median of {base.median_reviews:.0f}.",
            {"reviews": 0, **peer_obs}))
    elif reviews < base.p25_reviews:
        pts += 16
        ev.append(Evidence("gbp", "reviews_bottom_quartile", "high", 16,
            f"{reviews} reviews puts them in the bottom 25% of {niche} businesses in "
            f"{where} (median is {base.median_reviews:.0f}).",
            {"reviews": reviews, "p25": base.p25_reviews, **peer_obs}))
    elif reviews < base.median_reviews:
        pts += 9
        ev.append(Evidence("gbp", "reviews_below_median", "medium", 9,
            f"{reviews} reviews is below the {where} median of {base.median_reviews:.0f} "
            f"for {niche} businesses.",
            {"reviews": reviews, **peer_obs}))

    # Rating
    if rating and rating < 3.8:
        pts += 10
        ev.append(Evidence("gbp", "rating_poor", "high", 10,
            f"{rating} star average is below the 4.0 threshold most customers filter on. "
            f"Reputation management is the first fix here.",
            {"rating": rating}))
    elif rating and rating < 4.3:
        pts += 5
        ev.append(Evidence("gbp", "rating_mediocre", "medium", 5,
            f"{rating} stars trails the local median of {base.median_rating:.1f}.",
            {"rating": rating, "median": base.median_rating}))

    # No website linked on the GBP. Distinct from "has no website at all" —
    # plenty of businesses have a site but never linked it, which is a
    # 5-minute fix and a great opener because it's so obviously free money.
    if not b.get("website_url"):
        ev.append(Evidence("gbp", "no_website_on_gbp", "info", 0,
            "No website linked on the Google Business Profile. Google has nothing to "
            "crawl and no destination to send map-pack traffic to.",
            {"website_url": None}))

    if not b.get("phone"):
        pts += 6
        ev.append(Evidence("gbp", "no_phone", "high", 6,
            "No phone number on the profile — the map pack's single highest-intent action "
            "(tap to call) is unavailable.", {"phone": None}))

    if not b.get("has_hours"):
        pts += 8
        ev.append(Evidence("gbp", "no_hours", "high", 8,
            "No business hours listed. Google demotes incomplete profiles and customers "
            "skip listings that don't show whether they're open.", {"has_hours": False}))

    photos = b.get("photo_count") or 0
    if photos == 0:
        pts += 8
        ev.append(Evidence("gbp", "no_photos", "high", 8,
            "Zero photos on the profile. Listings with photos get materially more "
            "direction requests and clicks.", {"photo_count": 0}))
    elif photos < 5:
        pts += 4
        ev.append(Evidence("gbp", "few_photos", "medium", 4,
            f"Only {photos} photos on the profile — thin compared to well-managed listings.",
            {"photo_count": photos}))

    # Category depth
    types = b.get("types") or []
    meaningful = [t for t in types if t not in ("point_of_interest", "establishment")]
    if len(meaningful) <= 1:
        pts += 6
        ev.append(Evidence("gbp", "thin_categories", "medium", 6,
            "Only one Google category set. Secondary categories are one of the strongest "
            "and most underused map-pack ranking levers.", {"types": types}))

    # Category mismatch — the highest-leverage GBP fix there is, and one of the
    # few gaps a prospect can verify on their own phone in ten seconds.
    expected = C.VERTICAL_EXPECTED_TYPES.get(b.get("vertical") or "", set())
    ptype = b.get("primary_type") or ""
    # Only claim a mismatch when the business NAME confirms the trade. Without
    # that corroboration we'd be telling a plumbing company its category is
    # wrong because it turned up in an electrician search.
    trade_words = C.VERTICAL_SITE_WORDS.get(b.get("vertical") or "", [])
    name_confirms = any(w in (b.get("name") or "").lower() for w in trade_words)
    # Gate on CATEGORY_SIGNAL_VERIFIED: several verticals have expected types
    # that do not exist in the Places API taxonomy at all, so the comparison
    # below would flag every business in them. See the config comment.
    category_signal_usable = (b.get("vertical") or "") in C.CATEGORY_SIGNAL_VERIFIED
    if category_signal_usable and expected and ptype and ptype not in expected and name_confirms:
        if ptype in C.GENERIC_TYPES:
            pts += 15
            ev.append(Evidence("gbp", "category_generic", "critical", 15,
                f"Their Google primary category is \"{ptype.replace('_',' ')}\" rather than "
                f"{sorted(expected)[0].replace('_',' ')}. Primary category is the heaviest "
                f"map-pack ranking factor — this alone can keep them out of the results "
                f"for their own trade.",
                {"primary_type": ptype, "expected": sorted(expected)}))
        else:
            pts += 8
            ev.append(Evidence("gbp", "category_mismatch", "high", 8,
                f"Google has them filed as \"{ptype.replace('_',' ')}\", which doesn't match "
                f"the work they advertise. Category alignment is one of the strongest "
                f"map-pack levers.",
                {"primary_type": ptype, "expected": sorted(expected)}))

    if b.get("business_status") == "CLOSED_TEMPORARILY":
        pts += 3
        ev.append(Evidence("gbp", "temporarily_closed", "info", 3,
            "Profile is marked temporarily closed — may be stale and suppressing rankings.",
            {"business_status": "CLOSED_TEMPORARILY"}))

    return _normalize(pts, GBP_MAX_POINTS), ev


# ---------------------------------------------------------------------------
# Website gaps — 40% of score
# ---------------------------------------------------------------------------
def score_website(b: dict, w, base: Baseline) -> tuple[int | None, list]:
    """Website gap axis. Returns None when the site could not be audited."""
    ev: list = []
    pts = 0
    name = b.get("name") or "This business"
    profile = V.niche_profile(b.get("vertical"))

    if w is None or getattr(w, "crawl_error", None) == "no_website":
        # The single strongest signal in the entire model. No website means the
        # full website-build engagement is on the table, not just a retainer.
        ev.append(Evidence("website", "no_website", "critical", NO_WEBSITE_AXIS_SCORE,
            f"{name} has no website at all. Every map-pack impression they earn has "
            f"nowhere to convert. This is a full build opportunity.", {"website": None}))
        return NO_WEBSITE_AXIS_SCORE, ev

    if not w.is_reachable:
        # A bot filter turning us away is NOT evidence the site is broken.
        # Verified in testing: 2 of 3 sites flagged "down" were healthy behind a
        # WAF. Claiming downtime to a prospect whose site works is worse than
        # saying nothing, so blocked sites get a neutral, honest treatment and a
        # manual-check flag instead of a headline finding.
        if (w.crawl_error or "").startswith("blocked_"):
            ev.append(Evidence("website", "crawl_blocked", "info", 0,
                "Their site blocked automated access, so it could not be audited. "
                "Needs a manual look before outreach — do not claim it is down.",
                {"http_status": w.http_status, "error": w.crawl_error}))
            # Score on profile signals alone rather than guessing about the
            # website. None (not 0) so the lead isn't halved for being blocked.
            return None, ev

        if (w.crawl_error or "").startswith("profile_link_"):
            ev.append(Evidence("website", "broken_profile_link", "critical", BROKEN_LINK_AXIS_SCORE,
                f"The website link on {name}'s Google profile leads to an error page "
                f"(status {w.http_status}), although the homepage itself loads. "
                f"Everyone who taps 'Website' on Google lands on a dead page.",
                {"http_status": w.http_status, "linked_url": b.get("website_url"),
                 "working_url": w.redirects_to}))
            return BROKEN_LINK_AXIS_SCORE, ev

        ev.append(Evidence("website", "site_down", "critical", SITE_DOWN_AXIS_SCORE,
            f"Their website does not load (status {w.http_status or 'unreachable'}). "
            f"They are paying for a domain that actively loses them customers.",
            {"http_status": w.http_status, "error": w.crawl_error}))
        return SITE_DOWN_AXIS_SCORE, ev

    if getattr(w, "site_source", "gbp") in ("found", "manual"):
        # The business HAS a site; Google's profile just doesn't link to it.
        # Never call this "no website". It's a strong, accurate opener.
        pts += UNLISTED_SITE_POINTS
        ev.append(Evidence("gbp", "website_not_on_gbp", "high", UNLISTED_SITE_POINTS,
            f"{name} has a website ({w.resolved_url}), but it isn't linked on their Google "
            f"profile, so people on Google Maps can't get to it.",
            {"found_url": w.resolved_url}))

    if not w.has_ssl:
        pts += 8
        ev.append(Evidence("website", "no_ssl", "high", 8,
            "No HTTPS. Chrome shows a 'Not Secure' warning to every visitor and Google "
            "treats HTTPS as a ranking signal.", {"has_ssl": False}))

    # Local SEO structure — the Lilos service line, stated as findings
    if not w.has_localbusiness_schema:
        pts += 10
        ev.append(Evidence("website", "no_localbusiness_schema", "high", 10,
            "No LocalBusiness schema markup. Google can't reliably connect the site to "
            "the Business Profile, which weakens the entity signal behind map rankings.",
            {"schema_types": w.schema_types}))

    if not w.has_service_pages:
        pts += 9
        ev.append(Evidence("website", "no_service_pages", "high", 9,
            f"No dedicated {profile['offering_label']} found. A page per "
            f"{profile['offering_singular']} gives searches for that specific "
            f"{profile['offering_singular']} somewhere relevant to land.",
            {"has_service_pages": False, "label": profile["offering_label"],
             "sitemap_urls": getattr(w, "sitemap_url_count", None)}))

    if not w.has_city_pages:
        pts += 8
        ev.append(Evidence("website", "no_city_pages", "high", 8,
            f"No {profile['location_label']} found. Searches that name a nearby town "
            f"or neighborhood have no page on the site written for them.",
            {"has_city_pages": False, "label": profile["location_label"]}))

    if w.nap_matches_gbp is False:
        pts += 7
        ev.append(Evidence("website", "nap_mismatch", "high", 7,
            f"Phone on the website doesn't match the Google Business Profile "
            f"({w.nap_phone_on_site} vs {b.get('phone')}). NAP inconsistency directly "
            f"suppresses local rankings.",
            {"site_phone": w.nap_phone_on_site, "gbp_phone": b.get("phone")}))

    if not w.has_gbp_link:
        pts += 3
        ev.append(Evidence("website", "no_gbp_link", "low", 3,
            "Site doesn't link to the Google Business Profile — a free reinforcing signal "
            "they're leaving on the table.", {"has_gbp_link": False}))

    # On-page fundamentals
    if not w.title:
        pts += 7
        ev.append(Evidence("website", "no_title", "critical", 7,
            "Homepage has no title tag — the single most important on-page SEO element.",
            {"title": None}))
    elif w.title_length and (w.title_length < 20 or w.title_length > 65):
        pts += 3
        ev.append(Evidence("website", "title_length", "low", 3,
            f"Title tag is {w.title_length} characters ({'too short' if w.title_length < 20 else 'truncated in results'}).",
            {"title_length": w.title_length, "title": w.title}))

    if not w.meta_description:
        pts += 4
        ev.append(Evidence("website", "no_meta_description", "medium", 4,
            "No meta description. Google writes its own snippet, so they have no control "
            "over their search result copy.", {"meta_description": None}))

    if w.h1_count == 0:
        pts += 4
        ev.append(Evidence("website", "no_h1", "medium", 4,
            "No H1 heading on the homepage.", {"h1_count": 0}))
    elif w.h1_count > 1:
        pts += 2
        ev.append(Evidence("website", "multiple_h1", "low", 2,
            f"{w.h1_count} H1 tags on the homepage dilutes topical focus.",
            {"h1_count": w.h1_count}))

    if w.word_count < 300:
        pts += 5
        ev.append(Evidence("website", "thin_content", "medium", 5,
            f"Homepage has roughly {w.word_count} words. Thin content struggles to rank "
            f"for anything competitive.", {"word_count": w.word_count}))

    # Performance
    if w.psi_performance is not None:
        if w.psi_performance < 30:
            pts += 12
            ev.append(Evidence("website", "psi_mobile_critical", "critical", 12,
                f"Mobile PageSpeed score of {w.psi_performance}/100. Most visitors leave "
                f"before the page renders — and mobile is where local search happens.",
                {"psi_performance": w.psi_performance, "lcp_ms": w.psi_lcp_ms}))
        elif w.psi_performance < 50:
            pts += 8
            ev.append(Evidence("website", "psi_mobile_poor", "high", 8,
                f"Mobile PageSpeed score of {w.psi_performance}/100 — below Google's "
                f"'needs improvement' line.",
                {"psi_performance": w.psi_performance, "lcp_ms": w.psi_lcp_ms}))
    if w.psi_seo is not None and w.psi_seo < 80:
        pts += 5
        ev.append(Evidence("website", "psi_seo_low", "medium", 5,
            f"Lighthouse SEO score of {w.psi_seo}/100 — technical issues are holding the "
            f"site back independent of content.", {"psi_seo": w.psi_seo}))

    # Platform
    if w.is_template_builder:
        pts += 5
        ev.append(Evidence("website", "template_builder", "medium", 5,
            f"Site is built on {w.cms_detected.title()}. They already value having a site, "
            f"but the platform caps what's achievable on local SEO — a clean rebuild pitch.",
            {"cms": w.cms_detected}))

    if not w.has_contact_form and not getattr(w, "has_online_booking", False):
        pts += 6
        ev.append(Evidence("website", "no_contact_form", "high", 6,
            "No contact form or online booking found. Visitors who won't call on the "
            "spot have no other way to reach out.",
            {"has_contact_form": False}))

    for item in SS.findings(getattr(w, "site_signals", None), V.vertical_profile(b.get("vertical") or "")):
        pts += item["points"]
        ev.append(Evidence("website", item["signal"], item["severity"], item["points"],
                           item["finding"], item["observed"]))

    return _normalize(pts, WEBSITE_MAX_POINTS), ev


# ---------------------------------------------------------------------------
# Reachability — 20%, and a hard gate on tier
# ---------------------------------------------------------------------------
def score_reachability(b: dict, w) -> tuple[int, list]:
    ev: list = []
    pts = 0

    emails = list(getattr(w, "emails_found", []) or []) if w else []
    if emails:
        pts += 45
        ev.append(Evidence("reachability", "email_found", "info", 45,
            f"Direct email available: {emails[0]}", {"emails": emails}))
    # Phone is weighted on par with email: for home-service businesses, calling
    # is a genuinely viable channel (and feeds the speed-to-lead automation),
    # so a phone-only lead shouldn't be treated as half-unreachable.
    if b.get("phone"):
        pts += 45
        ev.append(Evidence("reachability", "phone_available", "info", 45,
            f"Phone: {b['phone']}", {"phone": b["phone"]}))
    if w and getattr(w, "has_online_booking", False):
        pts += 15
        ev.append(Evidence("reachability", "online_booking", "info", 15,
            f"Online booking via {w.booking_provider or 'a scheduling tool'}",
            {"provider": w.booking_provider}))
    elif w and w.contact_page_url:
        pts += 15
        ev.append(Evidence("reachability", "contact_form", "info", 15,
            f"Contact form at {w.contact_page_url}", {"url": w.contact_page_url}))
    socials = getattr(w, "social_profiles", {}) or {} if w else {}
    if socials:
        pts += 10
        ev.append(Evidence("reachability", "social_profiles", "info", 10,
            f"Social profiles: {', '.join(socials.keys())}", {"profiles": socials}))

    if pts == 0:
        ev.append(Evidence("reachability", "unreachable", "critical", 0,
            "No email, phone, form, or social profile found. Not actionable without "
            "manual research.", {}))

    return min(pts, 100), ev


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------
@dataclass
class ScoredLead:
    place_id: str
    total_score: int
    gbp_gap_score: int
    website_gap_score: int | None
    reachability_score: int
    tier: str
    headline_gap: str
    evidence: list
    activity: str = "unknown"
    labels: list = field(default_factory=list)
    market: str | None = None
    fit_score: int = 0
    qualification: str = "low_fit"
    qualification_reasons: list = field(default_factory=list)


def _headline(ev: list) -> str:
    """The single most pitchable finding — this becomes the email subject line."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    pitchable = [e for e in ev if e.category != "reachability"]
    if not pitchable:
        return "Profile and site review available"
    best = sorted(pitchable, key=lambda e: (order.get(e.severity, 9), -e.points))[0]
    return best.finding


# Points the optional paid enrichment can contribute. Kept separate so the axis
# maximum stays correct whether or not deep data exists — a lead with no deep
# data must not be penalised for the absence.
DEEP_MAX_POINTS = 34


def score_deep(deep: dict | None) -> tuple[int, list]:
    """Score the three qualifiers only available via paid enrichment.

    Absence of deep data yields (0, []) and does NOT count against a lead. These
    signals only ever add, so an un-enriched lead ranks on the free signals alone
    rather than looking artificially clean or artificially broken.
    """
    if not deep:
        return 0, []
    ev: list = []
    pts = 0

    if deep.get("services_count") == 0:
        pts += 12
        ev.append(Evidence("gbp_deep", "no_services_listed", "critical", 12,
            "Their Google profile has no Services filled in. Services are what "
            "Google matches against specific searches like \"panel upgrade near "
            "me\" — an empty list means they only compete on the category name.",
            {"services_count": 0}))
    elif not deep.get("services_have_descriptions"):
        pts += 5
        ev.append(Evidence("gbp_deep", "services_no_descriptions", "medium", 5,
            "Services are listed but none have descriptions. The description text "
            "is indexed and is where the specific search language belongs.",
            {"services_count": deep.get("services_count")}))

    if not deep.get("description_present"):
        pts += 8
        ev.append(Evidence("gbp_deep", "no_business_description", "high", 8,
            "No business description on the Google profile — 750 characters of "
            "keyword-relevant text left completely blank.", {"description": None}))
    elif (deep.get("description_length") or 0) < 250:
        pts += 3
        ev.append(Evidence("gbp_deep", "thin_business_description", "low", 3,
            f"Business description is only {deep['description_length']} of the 750 "
            f"characters Google allows.", {"length": deep.get("description_length")}))

    rate = deep.get("owner_reply_rate")
    sampled = deep.get("reviews_sampled") or 0
    if sampled >= 5 and rate is not None:
        if rate == 0:
            pts += 14
            ev.append(Evidence("gbp_deep", "no_review_replies", "critical", 14,
                f"They haven't replied to a single one of their last {sampled} "
                f"reviews. Google has said responding to reviews improves local "
                f"visibility, and customers read the replies as much as the reviews.",
                {"sampled": sampled, "replied": 0}))
        elif rate < 0.34:
            pts += 8
            ev.append(Evidence("gbp_deep", "few_review_replies", "high", 8,
                f"Only {deep['reviews_with_owner_reply']} of their last {sampled} "
                f"reviews got a reply.",
                {"sampled": sampled, "replied": deep["reviews_with_owner_reply"]}))

    if deep.get("is_claimed") is False:
        pts += 10
        ev.append(Evidence("gbp_deep", "unclaimed_profile", "critical", 10,
            "The Google Business Profile appears unclaimed — anyone can suggest "
            "edits and they can't post, reply, or see their own insights.",
            {"is_claimed": False}))

    return pts, ev


def activity_label(b: dict) -> str:
    """How recently the listing shows life. A lower bound: see config.ACTIVITY_TIERS."""
    d = b.get("last_review_days")
    if d is None:
        return "no reviews" if not (b.get("review_count") or 0) else "unknown"
    for limit, label in C.ACTIVITY_TIERS:
        if d <= limit:
            return label
    return C.ACTIVITY_TIERS[-1][1]


def _site_is_live(w) -> bool:
    """A site that turned our crawler away still exists; only its contents are unknown."""
    if w is None:
        return False
    return bool(getattr(w, "is_reachable", False)
                or (getattr(w, "crawl_error", None) or "").startswith("blocked_"))


def fit_score(b: dict, w, base: Baseline | None) -> tuple[int, list[str]]:
    """0-100: is this a real, working business that could buy? Plus the reasons."""
    reasons: list[str] = []
    label = activity_label(b)
    reviews = b.get("review_count") or 0
    p25 = base.p25_reviews if base else 0
    median = base.median_reviews if base else 0
    p75 = base.p75_reviews if base else 0
    at_median = bool(reviews) and reviews >= median

    activity = {"active": 40, "steady": 34, "quiet": 20, "stale": 5,
                "unknown": 24, "no reviews": 0}[label]
    # Google returns the most relevant reviews, not the newest, so an old sample
    # on a well-reviewed business with a working site proves nothing against it.
    if label in {"quiet", "stale"} and at_median and _site_is_live(w):
        activity = max(activity, 24)
    if activity >= 34:
        reasons.append("Recently active on Google")
    elif label == "no reviews":
        reasons.append("No reviews yet, so activity can't be confirmed")
    elif activity <= 5:
        reasons.append("No recent activity found")

    if not reviews:
        volume = 0
    elif reviews >= p75:
        volume = C.FIT_MAX["reviews"]
    elif at_median:
        volume = 25
    elif reviews >= max(p25, C.FIT_SOLID_REVIEWS):
        volume = 15
    else:
        volume = 5
    if volume >= 25:
        reasons.append(f"{reviews} reviews, at or above the local median of {median:.0f}")
    elif reviews:
        reasons.append(f"{reviews} reviews, below the local median of {median:.0f}")

    site = C.FIT_MAX["website"] if _site_is_live(w) else 0
    rating = float(b.get("rating") or 0)
    stars = C.FIT_MAX["rating"] if rating >= 4.0 else 5 if rating >= 3.5 else 0
    profile = C.FIT_MAX["profile"] if b.get("phone") and b.get("has_hours") else 0
    return min(100, activity + volume + site + stars + profile), reasons


def qualify(b: dict, w, fit: int, evidence: list, reach: int) -> tuple[str, list[str]]:
    """The verdict on a lead, with plain reasons. Order is the order to fix them in."""
    signals = {e.signal for e in evidence}
    gaps = [e for e in evidence if e.category != "reachability" and e.points > 0]
    emails = list(getattr(w, "emails_found", []) or []) if w else []
    if reach == 0:
        return "no_contact", ["No email, phone, form or social profile found"]
    if b.get("is_franchise"):
        return "franchise", ["National brand or franchise"]
    if fit < C.QUALIFY_MIN_FIT:
        return "low_fit", ["Not enough evidence yet that this is an active business"]
    if "crawl_blocked" in signals and not emails:
        return "verify_first", ["The site blocked our crawler, so it needs a quick look by hand"]
    if not gaps:
        return "no_gap", ["No clear gap to pitch: the profile and site look healthy"]
    if not emails:
        return "call_first", ["Good fit, but no email found: call them or add an email"]
    return "qualified", [f"Good fit with {len(gaps)} provable gap{'s' if len(gaps) != 1 else ''}"]


def reachability_multiplier(r: int) -> float:
    """Map a 0-100 reachability score onto a 0.40-1.00 discount factor.

    Never zero: an unreachable business with glaring gaps is still worth manual
    research, it just shouldn't outrank a workable lead. The floor of 0.40 says
    "heavily discounted, not discarded."
    """
    return 0.40 + 0.60 * (min(max(r, 0), 100) / 100)


try:
    from .scoring_labels import LABEL_NAMES, REAL_GAP_SIGNALS  # noqa: F401
except ImportError:  # pipeline scripts are also executed directly
    from scoring_labels import LABEL_NAMES, REAL_GAP_SIGNALS  # noqa: F401


def lead_labels(b: dict, w, base: Baseline | None, evidence: list,
                activity: str, reach: int) -> list[str]:
    """Plain labels that explain a lead. Labels never remove a lead."""
    labels: list[str] = []
    signals = {e.signal for e in evidence}
    reviews = b.get("review_count") or 0
    trading = b.get("last_review_days") is not None and b["last_review_days"] <= 365
    real_gaps = len(signals & REAL_GAP_SIGNALS)

    if trading:
        labels.append("trading")
    if base is not None and trading and reviews >= base.median_reviews and real_gaps >= 2:
        labels.append("established")
    if base is not None and reviews and reviews >= base.p75_reviews:
        labels.append("strong_reviews")
    if "no_website" in signals:
        labels.append("no_website")
    if signals & {"site_down", "broken_profile_link"}:
        labels.append("site_down")
    if "website_not_on_gbp" in signals:
        labels.append("site_not_on_google")
    if signals & {"crawl_blocked", "site_down", "nap_mismatch"}:
        labels.append("verify_first")
    emails = list(getattr(w, "emails_found", []) or []) if w else []
    if emails:
        labels.append("email_found")
    elif b.get("phone"):
        labels.append("phone_only")
    if reach == 0:
        labels.append("no_contact")
    if w is not None and getattr(w, "has_online_booking", False):
        labels.append("online_booking")
    if b.get("is_franchise"):
        labels.append("franchise")
    if reviews == 0:
        labels.append("no_reviews")
    rating = b.get("rating")
    if rating and float(rating) < 4.0:
        labels.append("low_rating")
    if w is not None and getattr(w, "is_template_builder", False):
        labels.append("template_site")
    return labels


def score_lead(b: dict, w, base: Baseline, deep: dict | None = None) -> ScoredLead:
    g_raw, ev_g = score_gbp(b, base)
    s, ev_s = score_website(b, w, base)
    r, ev_r = score_reachability(b, w)

    # Deep signals only ever add to the GBP axis, so an un-enriched lead isn't
    # penalised for missing data it was never eligible for.
    d_pts, ev_d = score_deep(deep)
    g = min(100, g_raw + _normalize(d_pts, GBP_MAX_POINTS))
    ev_g = ev_g + ev_d

    if s is None:
        # Website couldn't be audited (bot-blocked): rank on the profile alone
        # instead of treating the site as perfect.
        opportunity = float(g)
    else:
        worse, better = max(g, s), min(g, s)
        w_axis = C.OPPORTUNITY_WORST_AXIS_WEIGHT
        opportunity = worse * w_axis + better * (1 - w_axis)
    # A nitpick or two isn't a sales opportunity: rescale so the noise floor is zero.
    floor = C.OPPORTUNITY_NOISE_FLOOR
    opportunity = max(0.0, opportunity - floor) * 100 / (100 - floor)
    fit, fit_reasons = fit_score(b, w, base)
    act_label = activity_label(b)
    franchise_mult = C.FRANCHISE_MULTIPLIER if b.get("is_franchise") else 1.0
    total = round(math.sqrt(fit * opportunity) * reachability_multiplier(r) * franchise_mult)

    d = b.get("last_review_days")
    if act_label in ("active", "steady"):
        ev_r.append(Evidence("reachability", "business_active", "info", 0,
            f"Live business — most recent review {d} days ago.",
            {"last_review_days": d, "activity": act_label}))
    elif act_label == "stale":
        ev_r.append(Evidence("reachability", "listing_stale", "info", 0,
            f"Newest review in Google's sample is {d} days old. Google returns "
            f"the most RELEVANT reviews rather than the newest, so this is a "
            f"weak signal — check the profile before assuming they're inactive.",
            {"last_review_days": d}))
    elif act_label == "no reviews":
        ev_r.append(Evidence("reachability", "no_review_history", "info", 0,
            "No reviews at all, so no way to confirm the business is active. "
            "Could be new, could be abandoned.", {}))

    # Tier is a priority grade for working the list, never a filter. A lead
    # with no contact route keeps its grade and gets a "no_contact" label.
    tier = "D"
    for label, cutoff in C.TIER_CUTOFFS:
        if total >= cutoff:
            tier = label
            break

    evidence = ev_g + ev_s + ev_r
    verdict, verdict_reasons = qualify(b, w, fit, evidence, r)
    labels = lead_labels(b, w, base, evidence, act_label, r)
    return ScoredLead(
        place_id=b["place_id"],
        total_score=int(total),
        gbp_gap_score=g,
        website_gap_score=s,
        reachability_score=r,
        tier=tier,
        headline_gap=_headline(ev_g + ev_s),
        evidence=evidence,
        activity=act_label,
        labels=labels,
        market=b.get("market"),
        fit_score=fit,
        qualification=verdict,
        qualification_reasons=verdict_reasons + fit_reasons,
    )


def score_all(businesses: list, enrichment: dict, geo_label: str | None = None,
              deep: dict | None = None) -> tuple[list, dict]:
    baselines = compute_baselines(businesses, geo_label)
    deep = deep or {}
    out = []
    for b in businesses:
        if geo_label and not b.get("market"):
            b = {**b, "market": geo_label}
        base = baseline_for(baselines, b.get("vertical") or "unknown", b.get("market"))
        if base is None:
            continue
        out.append(score_lead(b, enrichment.get(b["place_id"]), base,
                              deep.get(b["place_id"])))
    out.sort(key=lambda s: s.total_score, reverse=True)
    return out, baselines
