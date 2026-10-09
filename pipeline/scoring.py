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

4. Reachability is a MULTIPLIER, not an addend. This is the correction that
   matters most. If reachability is just another weighted component, a
   perfectly-optimized business with a good contact page collects "opportunity"
   points for being easy to reach — which is nonsense. Reachability doesn't
   create opportunity, it determines whether you can act on it. So:

       opportunity = (gbp_gap + website_gap) / 2
       total       = opportunity * reachability_multiplier

   A flawless business scores near zero no matter how reachable. An unreachable
   business with every gap in the book gets heavily discounted, because a lead
   you cannot contact is not a lead.

5. Axes are normalized against their REALISTIC maximum, not against 100. The
   GBP axis can only emit 77 raw points and the website axis 93, so dividing by
   100 would silently compress every score and make the tier cutoffs unreachable.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import config as C
import verticals as V

# Maximum raw points each axis can emit, used to normalize to 0-100.
# Derived by summing the mutually-compatible signals in each scorer:
#   GBP:     22 no_reviews + 10 rating_poor + 6 no_phone
#          +  8 no_hours + 8 no_photos + 6 thin_categories + 3 temp_closed
#          + 15 category_generic = 78
#   ("no website linked on GBP" carries 0 points: the website axis already
#    scores the missing site at 100, and counting it twice made no-website
#    leads crowd out everything else.)
#   WEBSITE:  8 no_ssl + 10 no_schema + 9 no_service + 8 no_city + 7 nap
#          +  3 no_gbp_link + 7 no_title + 4 no_meta + 4 no_h1 + 5 thin
#          + 12 psi_critical + 5 psi_seo + 5 template + 6 no_form = 93
# If you add or reweight a signal, update these or scores drift silently.
GBP_MAX_POINTS = 78
WEBSITE_MAX_POINTS = 93

# The two dominant website outcomes bypass the itemized path and map straight
# onto the top of the axis, because "no site" and "site is down" are strictly
# bigger opportunities than any accumulation of on-page nitpicks.
NO_WEBSITE_AXIS_SCORE = 100
SITE_DOWN_AXIS_SCORE = 85
BROKEN_LINK_AXIS_SCORE = 75


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


def activity_multiplier(b: dict) -> tuple[float, str]:
    """Discount by how dormant the listing looks.

    This replaces review-count-as-qualifier, which conflated two opposite
    prospects: a dead 2019 listing and a working business that never asks for
    reviews both show "3 reviews". Recency separates them, and only one of the
    two can buy anything.

    Not a hard filter — a quiet listing attached to a real business is still
    worth a call, just not the top of the queue.
    """
    d = b.get("last_review_days")
    if d is None:
        if (b.get("review_count") or 0) == 0:
            return C.ACTIVITY_UNKNOWN_NO_REVIEWS, "no reviews"
        return C.ACTIVITY_UNKNOWN_HAS_REVIEWS, "unknown"
    for limit, mult, label in C.ACTIVITY_TIERS:
        if d <= limit:
            return mult, label
    return C.ACTIVITY_TIERS[-1][1], C.ACTIVITY_TIERS[-1][2]


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

    # Deep signals fold into the GBP axis, with the axis maximum widened to match
    # so an enriched lead isn't scored against a narrower scale than it can fill.
    d_pts, ev_d = score_deep(deep)
    if deep:
        g = _normalize(
            int(round(g_raw / 100 * GBP_MAX_POINTS)) + d_pts,
            GBP_MAX_POINTS + DEEP_MAX_POINTS,
        )
    else:
        g = g_raw
    ev_g = ev_g + ev_d

    if s is None:
        # Website couldn't be audited (bot-blocked): rank on the profile alone
        # instead of treating the site as perfect.
        opportunity = g
    else:
        opportunity = g * C.WEIGHTS["gbp"] + s * C.WEIGHTS["website"]
    act_mult, act_label = activity_multiplier(b)
    franchise_mult = C.FRANCHISE_MULTIPLIER if b.get("is_franchise") else 1.0
    total = round(opportunity * reachability_multiplier(r) * act_mult * franchise_mult)

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
        labels=lead_labels(b, w, base, evidence, act_label, r),
        market=b.get("market"),
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
