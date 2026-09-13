"""
Lilos Growth lead aggregator — configuration.

Everything geo/vertical-specific lives here so widening from the San Diego
electrician pilot to other markets is a config edit, not a code change.
"""
import os

# ---------------------------------------------------------------------------
# Credentials (injected at runtime via RunWithCredentials — never hardcode)
# ---------------------------------------------------------------------------
GOOGLE_API_KEY   = os.environ.get("GOOGLE_API_KEY", "")

# ---------------------------------------------------------------------------
# Google Places API (New)
# ---------------------------------------------------------------------------
PLACES_SEARCH_URL  = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
PSI_URL            = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# THE cost decision.
#
# Billing is per *request*, not per result. One Text Search call returns up to
# 20 places, and if the field mask includes Enterprise-tier fields, all 20 come
# back fully detailed for the price of a single Enterprise request ($35/1000).
#
# That is ~$1.75 per 1,000 businesses, versus ~$20 per 1,000 if we called Place
# Details per business. Same data. 10x cheaper. So we deliberately ask for the
# expensive fields *in the search call* and skip Place Details entirely for the
# bulk sweep.
#
# Enterprise-tier fields (these set the SKU): websiteUri, nationalPhoneNumber,
# rating, userRatingCount, regularOpeningHours.
SEARCH_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.photos",
    # --- Enterprise tier below; these are the whole point of the sweep ---
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.regularOpeningHours",
    # `reviews` returns up to 5 recent reviews WITH publishTime. That timestamp is
    # the single best liveness signal available: it separates a dormant listing
    # nobody has touched in three years from a working business that simply never
    # asks for reviews. Review COUNT cannot make that distinction, which is why it
    # was a poor qualifier. Bumps the SKU to Enterprise+Atmosphere ($40/1k vs $35),
    # still $0 at pilot volume.
    "places.reviews",
    # ---
    "nextPageToken",
])

# Cost model, verified Aug 2026. Per 1,000 requests, first volume tier.
COST_PER_1K = {
    "text_search_enterprise":   35.00,
    "text_search_pro":          32.00,
    "place_details_enterprise": 20.00,
    "place_details_pro":        17.00,
}
FREE_TIER_MONTHLY = {"essentials": 10_000, "pro": 5_000, "enterprise": 1_000}

MAX_PAGES_PER_QUERY = 3      # Google hard cap: 60 results / 3 pages
RESULTS_PER_PAGE    = 20

# ---------------------------------------------------------------------------
# Pilot target: San Diego County
# ---------------------------------------------------------------------------
GEO_LABEL = "San Diego County"

# Bounding box for San Diego County (approximate, trimmed to populated coastal
# and inland corridor — the eastern desert is mostly empty and would waste calls)
GEO_BBOX = {
    "min_lat": 32.53,   # US/Mexico border
    "max_lat": 33.51,   # Camp Pendleton / Riverside County line
    "min_lng": -117.32, # coast
    "max_lng": -116.75, # east of Ramona/Alpine; past this is desert
}

# Grid spacing. Text Search caps at 60 results per query, so in dense areas a
# coarse grid silently truncates and you never know what you missed. ~8km cells
# keep most vertical+cell combinations under the cap.
GRID_SPACING_KM = 8.0

# Cities used for query text — Text Search responds much better to
# "electrician in Carlsbad CA" than to a bare lat/lng radius nudge.
TARGET_CITIES = [
    "San Diego", "Carlsbad", "Oceanside", "Vista", "San Marcos", "Escondido",
    "Encinitas", "Solana Beach", "Del Mar", "Poway", "Rancho Bernardo",
    "Chula Vista", "National City", "La Mesa", "El Cajon", "Santee",
    "Lemon Grove", "Spring Valley", "Imperial Beach", "Coronado",
    "Ramona", "Alpine", "Lakeside", "Fallbrook", "Bonsall", "Julian",
]

# ---------------------------------------------------------------------------
# Verticals. Electrician leads because Wheyland Electric is the strongest
# case study — the outreach hook writes itself for that vertical.
# ---------------------------------------------------------------------------
VERTICALS = {
    "electrician": {
        "queries": ["electrician", "electrical contractor", "residential electrician"],
        "priority": 1,
        "case_study": "Wheyland Electric — 20 to 306 keywords and 1 to 29 top-3 rankings in 5 months",
    },
    "plumber": {
        "queries": ["plumber", "plumbing contractor", "emergency plumber"],
        "priority": 2,
        "case_study": None,
    },
    "hvac": {
        "queries": ["hvac contractor", "air conditioning repair", "heating and cooling"],
        "priority": 2,
        "case_study": None,
    },
    "roofing": {
        "queries": ["roofing contractor", "roof repair"],
        "priority": 3,
        "case_study": None,
    },
    "restoration": {
        "queries": ["water damage restoration", "fire damage restoration"],
        "priority": 2,
        "case_study": "Tamarack Restoration — 12 to 420 keywords in 12 months",
    },
    "landscaping": {
        "queries": ["landscaping contractor", "landscape design"],
        "priority": 3,
        "case_study": None,
    },
    "party_rentals": {
        "queries": ["party rentals", "event rentals"],
        "priority": 3,
        "case_study": "Kelari Party Rentals — 0 to 38 keywords, 8 top-3 from launch",
    },
    "handyman": {
        "queries": ["handyman service", "home repair service"],
        "priority": 3,
        "case_study": "Carlsbad Fix It",
    },
}

PILOT_VERTICALS = ["electrician"]

# ---------------------------------------------------------------------------
# Crawler etiquette. We crawl prospects' own public sites — ordinary, legal
# crawling — but only if we do it politely. Identify ourselves, respect
# robots.txt, rate limit, and cap pages per site.
# ---------------------------------------------------------------------------
USER_AGENT = "LilosGrowthBot/1.0 (+https://lilosgrowth.com/bot; local SEO audit crawler)"
CRAWL_TIMEOUT_S      = 15
CRAWL_DELAY_S        = 1.0     # per-domain politeness delay
CRAWL_MAX_PAGES      = 6       # home + contact + about + a few service pages
CRAWL_MAX_CONCURRENT = 8
RESPECT_ROBOTS       = True

CONTACT_PAGE_HINTS = [
    "contact", "contact-us", "contactus", "get-a-quote", "quote", "estimate",
    "about", "about-us", "schedule", "book",
]

# ---------------------------------------------------------------------------
# Scoring model
# ---------------------------------------------------------------------------
MODEL_VERSION = "v1.0"

# gbp and website split the "opportunity" score 50/50. Reachability is NOT a
# weight — it's applied as a multiplier afterwards (see scoring.py), because
# being easy to contact is not itself an opportunity.
WEIGHTS = {"gbp": 0.50, "website": 0.50}

# Provisional cutoffs. These are calibrated against synthetic fixtures and MUST
# be re-tuned once the first real sweep lands — the honest way to set them is to
# look at the actual score distribution and at which leads you'd personally call.
TIER_CUTOFFS = [("A", 45), ("B", 33), ("C", 22), ("D", 0)]

# Businesses we should not bother pitching.
EXCLUDE_BUSINESS_STATUS = ["CLOSED_PERMANENTLY"]

# National chains / franchises — they don't buy local SEO from a local agency.
# Filtering these out matters more than it sounds: they're heavily represented
# in map results and they pollute the top of a gap-based score because their
# local pages are often genuinely thin.
CHAIN_NAME_PATTERNS = [
    "mister sparky", "roto-rooter", "roto rooter", "benjamin franklin plumbing",
    "one hour heating", "ars/rescue rooter", "servpro", "servicemaster",
    "paul davis", "911 restoration", "home depot", "lowes", "lowe's",
    "sears", "aire serv", "mr. rooter", "mr rooter", "mr. electric",
    "mr electric", "mrelectric", "milestone", "mr. handyman", "mr handyman",
]


# ---------------------------------------------------------------------------
# Category mismatch detection
# ---------------------------------------------------------------------------
# Google's primaryType is the single heaviest map-pack ranking lever, and a
# surprising number of contractors are filed under something generic. A licensed
# electrician sitting under "general_contractor" is invisible for "electrician
# near me" no matter how good the rest of their profile is — and it's a
# fifteen-minute fix, which makes it an outstanding opening pitch.
VERTICAL_EXPECTED_TYPES = {
    "electrician":   {"electrician"},
    "plumber":       {"plumber"},
    "hvac":          {"hvac_contractor", "heating_contractor", "air_conditioning_contractor"},
    "roofing":       {"roofing_contractor"},
    "restoration":   {"general_contractor", "fire_damage_restoration_service",
                      "water_damage_restoration_service"},
    "landscaping":   {"landscaper", "landscape_designer", "lawn_care_service"},
    "party_rentals": {"party_equipment_rental_service", "event_venue"},
    "handyman":      {"handyman", "general_contractor"},
}

# Verticals whose expected primary types are CONFIRMED to exist in the Places
# (New) taxonomy. Gate every category claim on this set.
#
# Why this exists: VERTICAL_EXPECTED_TYPES was written from what Google's
# CATEGORY names look like, but the Places API type vocabulary is different and
# smaller. Probing the API directly (searchText with includedType) returns
# "Invalid included_type" for hvac_contractor, heating_contractor,
# air_conditioning_contractor, landscaper, landscape_designer, lawn_care_service,
# handyman, fire_damage_restoration_service and water_damage_restoration_service
# — none of those strings exist. An expected set that can never be matched makes
# EVERY business in that vertical look mis-categorised.
#
# Measured on the 2026-08-27 tri-vertical sweep: 0 of 417 HVAC businesses
# carried any expected HVAC type, and the model emitted a category claim against
# 301 of them — telling ~250 owners their primary category was wrong and naming
# a replacement category that does not exist. Plumber (334/390 typed `plumber`)
# and roofing (266/362 typed `roofing_contractor`) were unaffected.
#
# Verify with an includedType probe before adding a vertical here.
CATEGORY_SIGNAL_VERIFIED = {"electrician", "plumber", "roofing", "party_rentals"}

# Generic buckets that are *technically* valid but almost always the wrong
# primary category for a specialist trade.
GENERIC_TYPES = {
    "general_contractor", "contractor", "home_improvement_store",
    "point_of_interest", "establishment", "store", "business_center",
}

# Words we look for on the prospect's own website to corroborate what they
# actually do, so a mismatch claim rests on two sources rather than one.
VERTICAL_SITE_WORDS = {
    "electrician":   ["electric", "electrical", "electrician", "wiring", "panel upgrade"],
    "plumber":       ["plumb", "drain", "water heater", "repipe"],
    "hvac":          ["hvac", "air conditioning", "furnace", "heating", "mini split"],
    "roofing":       ["roof", "shingle", "re-roof"],
    "restoration":   ["restoration", "water damage", "mold", "fire damage"],
    "landscaping":   ["landscap", "hardscape", "irrigation", "lawn"],
    "party_rentals": ["rental", "party", "event", "tent", "bounce"],
    "handyman":      ["handyman", "home repair", "odd jobs"],
}

# ---------------------------------------------------------------------------
# Liveness thresholds (days since most recent review)
# ---------------------------------------------------------------------------
# Review COUNT is a bad qualifier: one review could be a dormant 2019 listing or
# a working business that never asks. Review RECENCY separates them.
# ASYMMETRIC BY DESIGN. Google returns the 5 most RELEVANT reviews, not the 5
# most recent, so this date is a lower bound: a recent review PROVES the
# business is trading, while an old one only fails to prove it. Confirmed-active
# therefore gets a real boost, and apparent-dormancy gets a mild discount rather
# than the heavy penalty a reliable signal would justify. Treating a lower bound
# as if it were exact would bury live businesses whose recent reviews simply
# weren't in the sample.
ACTIVITY_TIERS = [
    (90,   1.00, "active"),
    (365,  0.95, "steady"),
    (730,  0.85, "quiet"),
    (99999, 0.72, "stale"),
]
ACTIVITY_UNKNOWN_NO_REVIEWS = 0.62   # no reviews at all — genuinely ambiguous
ACTIVITY_UNKNOWN_HAS_REVIEWS = 0.90  # has reviews, none sampled: assume alive
