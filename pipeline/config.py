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
    "text_search_enterprise":   40.00,
    "text_search_pro":          32.00,
    "place_details_enterprise": 20.00,
    "place_details_pro":        17.00,
}
FREE_TIER_MONTHLY = {"essentials": 10_000, "pro": 5_000, "enterprise": 1_000}

MAX_PAGES_PER_QUERY = 3      # Google hard cap: 60 results / 3 pages
RESULTS_PER_PAGE    = 20

# ---------------------------------------------------------------------------
# Market scope
# ---------------------------------------------------------------------------
# Lead Desk is not tied to one metro. Every sweep names its own U.S. cities
# (canonical "City, ST, USA" labels from Places Autocomplete), and each lead is
# compared against businesses in the SAME niche and the SAME searched market.
#
# There is deliberately no default city list: a sweep without cities is an
# operator error, not a silent fallback to one region.
TARGET_CITIES: list[str] = []

# Label used only when a run has no city scope at all (legacy grid CLI runs).
DEFAULT_GEO_LABEL = "Custom market"

# Places Text Search is semantic, not a geofence. A business whose locality is a
# neighborhood or suburb of the searched city (e.g. "La Jolla" for "San Diego")
# is still in that market. Results within this radius of the searched market's
# center, in the same state, are kept and attributed to that market.
NEARBY_RADIUS_KM = 25.0

# Google caps one Text Search at 60 results (3 pages x 20). When a query comes
# back full, the market is denser than one query can see, so the area the
# results cover is split into smaller rectangles and searched again.
#
# OFF by default: splitting multiplies search calls (up to 4x per level) far
# beyond the estimate shown on the Sweeps page. The 2026-10-08 Scottsdale med
# spa sweep made 136 calls against an on-screen max of 9 because of it.
SPLIT_SATURATED_QUERIES = False
MAX_SPLIT_DEPTH = 1          # if enabled: 1 split = 4 extra calls per capped query

# Hard ceiling on billable search calls per sweep, whatever the settings. A
# sweep can never spend more than queries x cities x MAX_PAGES_PER_QUERY, the
# same "max with pagination" number the Sweeps page shows before you start.

# A market needs at least this many businesses in a niche before its own
# medians are trusted; below that, the niche-wide medians for the run are used.
MIN_MARKET_BASELINE_SAMPLE = 8

# Legacy grid mode (CLI only, disabled in the app). Requires an explicit box;
# nothing defaults to a particular region any more.
GEO_BBOX: dict | None = None
GRID_SPACING_KM = 8.0

# ---------------------------------------------------------------------------
# Niche profiles. A profile tells the crawler and scorer what "offering pages"
# and "location pages" look like for that kind of business, and how to word
# findings. Any niche can be swept; niches without a preset use the generic
# profile, which is intentionally broad so it errs toward NOT claiming a gap.
# ---------------------------------------------------------------------------
NICHE_PROFILES = {
    "home_service": {
        "offering_label": "service pages",
        "offering_singular": "service",
        "location_label": "service-area pages",
        "offering_words": [
            "service", "repair", "install", "replacement", "maintenance",
            "inspection", "upgrade", "cleaning", "emergency", "remodel",
            "panel", "wiring", "lighting", "ev-charger", "water-heater", "drain",
            "repipe", "leak", "sewer", "ac-", "air-conditioning", "furnace",
            "heating", "heat-pump", "duct", "mini-split", "roof", "gutter",
            "landscap", "irrigation", "hardscape", "lawn", "tree", "restoration",
            "water-damage", "mold", "fire-damage", "pest", "pool", "solar",
            "garage-door", "fence", "concrete", "paint", "handyman",
            "rental", "tent", "bounce", "party",
        ],
    },
    "medical_aesthetic": {
        "offering_label": "treatment pages",
        "offering_singular": "treatment",
        "location_label": "location pages",
        "offering_words": [
            "treatment", "service", "botox", "dysport", "filler", "injectable",
            "laser", "facial", "hydrafacial", "microneedling", "peel", "prp",
            "coolsculpt", "body-contour", "sculpt", "skin", "hair-removal",
            "iv-therapy", "weight-loss", "semaglutide", "tirzepatide", "lip",
            "rejuvenation", "tightening", "morpheus", "ipl", "medspa", "med-spa",
            "wellness", "hormone",
        ],
    },
    "dental": {
        "offering_label": "procedure pages",
        "offering_singular": "procedure",
        "location_label": "location pages",
        "offering_words": [
            "service", "treatment", "implant", "invisalign", "aligner",
            "orthodont", "braces", "crown", "veneer", "whitening", "cleaning",
            "root-canal", "endodont", "extraction", "wisdom", "emergency",
            "pediatric", "cosmetic", "denture", "bridge", "periodont", "gum",
            "sedation", "family-dentistry", "general-dentistry", "smile",
        ],
    },
    "real_estate": {
        "offering_label": "buyer, seller and listing pages",
        "offering_singular": "page",
        "location_label": "neighborhood or community pages",
        "offering_words": [
            "listing", "homes-for-sale", "for-sale", "property", "properties",
            "buy", "buyer", "sell", "seller", "home-value", "home-valuation",
            "valuation", "search", "idx", "mls", "relocation", "luxury",
            "condo", "new-construction", "open-house", "sold", "featured",
        ],
    },
    "legal": {
        "offering_label": "practice-area pages",
        "offering_singular": "practice area",
        "location_label": "office or location pages",
        "offering_words": [
            "practice-area", "practice", "injury", "accident", "car-accident",
            "truck", "wrongful-death", "slip", "malpractice", "workers-comp",
            "criminal", "dui", "family-law", "divorce", "custody", "estate",
            "probate", "trust", "will", "bankruptcy", "immigration",
            "employment", "business-law", "real-estate-law", "litigation",
        ],
    },
    "wellness_health": {
        "offering_label": "service pages",
        "offering_singular": "service",
        "location_label": "location pages",
        "offering_words": [
            "service", "treatment", "therapy", "condition", "adjustment",
            "chiropractic", "physical-therapy", "massage", "acupuncture",
            "sports", "injury", "pain", "back", "neck", "sciatica", "rehab",
            "spinal", "decompression", "prenatal", "pediatric", "wellness",
        ],
    },
    "auto": {
        "offering_label": "service pages",
        "offering_singular": "service",
        "location_label": "location pages",
        "offering_words": [
            "service", "repair", "brake", "oil-change", "transmission",
            "diagnostic", "engine", "tire", "alignment", "smog", "inspection",
            "detail", "tint", "body", "collision", "paint", "maintenance",
        ],
    },
}

# Custom niches have no preset vocabulary, so the generic profile is the UNION
# of every profile's offering words plus general business words. Over-detecting
# offering pages only means we stay quiet; under-detecting would put a false
# claim in front of a business owner.
_GENERIC_WORDS = [
    "service", "services", "product", "products", "menu", "pricing", "price",
    "package", "packages", "what-we-do", "offering", "solutions", "specialt",
    "programs", "classes", "catering", "shop", "store", "collection",
]
NICHE_PROFILES["generic_local_business"] = {
    "offering_label": "pages for individual services or offerings",
    "offering_singular": "offering",
    "location_label": "location pages",
    "offering_words": sorted(
        {w for prof in NICHE_PROFILES.values() for w in prof["offering_words"]}
        | set(_GENERIC_WORDS)
    ),
}

# Words that mark a page as a location / market page in any niche, in addition
# to the business's own city and the searched market's city.
LOCATION_PAGE_WORDS = [
    "service-area", "service-areas", "areas-we-serve", "areas-served",
    "areas", "locations", "location", "neighborhood", "neighborhoods",
    "communities", "community", "cities", "near-me", "serving",
]

# ---------------------------------------------------------------------------
# Niche presets. Presets add curated query expansion and a profile; they are
# NOT an allow-list. Any operator-entered niche can be swept and falls back to
# the generic profile. `case_study` is optional proof copy for that niche and is
# omitted everywhere when None.
# ---------------------------------------------------------------------------
VERTICALS = {
    "electrician": {
        "queries": ["electrician", "electrical contractor", "residential electrician"],
        "priority": 1,
        "profile": "home_service",
        "case_study": "Wheyland Electric — 20 to 306 keywords and 1 to 29 top-3 rankings in 5 months",
    },
    "plumber": {
        "queries": ["plumber", "plumbing contractor", "emergency plumber"],
        "priority": 2,
        "profile": "home_service",
        "case_study": None,
    },
    "hvac": {
        "queries": ["hvac contractor", "air conditioning repair", "heating and cooling"],
        "priority": 2,
        "profile": "home_service",
        "case_study": None,
    },
    "roofing": {
        "queries": ["roofing contractor", "roof repair"],
        "priority": 3,
        "profile": "home_service",
        "case_study": None,
    },
    "restoration": {
        "queries": ["water damage restoration", "fire damage restoration"],
        "priority": 2,
        "profile": "home_service",
        "case_study": "Tamarack Restoration — 12 to 420 keywords in 12 months",
    },
    "landscaping": {
        "queries": ["landscaping contractor", "landscape design"],
        "priority": 3,
        "profile": "home_service",
        "case_study": None,
    },
    "party_rentals": {
        "queries": ["party rentals", "event rentals"],
        "priority": 3,
        "profile": "home_service",
        "case_study": "Kelari Party Rentals — 0 to 38 keywords, 8 top-3 from launch",
    },
    "handyman": {
        "queries": ["handyman service", "home repair service"],
        "priority": 3,
        "profile": "home_service",
        "case_study": None,
    },
    "real_estate_agent": {
        "queries": ["real estate agent", "realtor", "real estate team"],
        "priority": 3,
        "profile": "real_estate",
        "case_study": None,
    },
    "med_spa": {
        "queries": ["med spa", "medical spa", "botox clinic"],
        "priority": 3,
        "profile": "medical_aesthetic",
        "case_study": None,
    },
    "dentist": {
        "queries": ["dentist", "dental office", "cosmetic dentist"],
        "priority": 3,
        "profile": "dental",
        "case_study": None,
    },
    "chiropractor": {
        "queries": ["chiropractor", "chiropractic clinic"],
        "priority": 3,
        "profile": "wellness_health",
        "case_study": None,
    },
    "personal_injury_attorney": {
        "queries": ["personal injury attorney", "car accident lawyer"],
        "priority": 3,
        "profile": "legal",
        "case_study": None,
    },
    "auto_repair": {
        "queries": ["auto repair shop", "auto mechanic"],
        "priority": 3,
        "profile": "auto",
        "case_study": None,
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
CRAWL_CACHE_MAX_AGE_DAYS = 30  # a re-swept site older than this is crawled again
SITE_CRAWL_CAP_S     = 75      # hard wall-clock cap for one site, all its pages included
RESPECT_ROBOTS       = True

CONTACT_PAGE_HINTS = [
    "contact", "contact-us", "contactus", "get-a-quote", "quote", "estimate",
    "about", "about-us", "schedule", "book",
]

# ---------------------------------------------------------------------------
# Scoring model
# ---------------------------------------------------------------------------
MODEL_VERSION = "v3.0"

# The worse of the two axes leads. A healthy Google profile must not cancel out
# a weak website: that average is what graded established businesses Tier D.
# Reachability is NOT a weight — it's a multiplier (see scoring.py), because being
# easy to contact is not itself an opportunity.
OPPORTUNITY_WORST_AXIS_WEIGHT = 0.70
OPPORTUNITY_NOISE_FLOOR = 10

# Points at which an axis reads "clearly underserved". No real business trips
# every signal at once, so scaling to the theoretical maximum compressed every
# score into the bottom third of the range.
GBP_SATURATION_POINTS = 45
WEBSITE_SATURATION_POINTS = 55

# Tiers rank the list; `qualification` (below) says what to do with a lead.
TIER_CUTOFFS = [("A", 45), ("B", 33), ("C", 22), ("D", 0)]

# Fit: is this a real, working business that could buy? Max 100.
FIT_MAX = {"activity": 40, "reviews": 30, "website": 15, "rating": 10, "profile": 5}
QUALIFY_MIN_FIT = 45
FIT_SOLID_REVIEWS = 10  # enough reviews to count as a real customer base anywhere

QUALIFICATION_LABELS = {
    "qualified": "Qualified",
    "call_first": "Qualified, call first",
    "verify_first": "Check site first",
    "low_fit": "Too early",
    "no_gap": "Nothing to pitch",
    "franchise": "Franchise",
    "no_contact": "No contact route",
}

# Businesses we should not bother pitching.
EXCLUDE_BUSINESS_STATUS = ["CLOSED_PERMANENTLY"]

# National chains / franchises rarely buy local SEO from a local agency, and
# their thin local pages inflate gap scores. They are KEPT and labelled
# "franchise" (with a priority discount) rather than dropped, so the operator
# decides — some franchise owners do buy locally.
CHAIN_NAME_PATTERNS = [
    "mister sparky", "roto-rooter", "roto rooter", "benjamin franklin plumbing",
    "one hour heating", "ars/rescue rooter", "servpro", "servicemaster",
    "paul davis", "911 restoration", "home depot", "lowes", "lowe's",
    "sears", "aire serv", "mr. rooter", "mr rooter", "mr. electric",
    "mr electric", "mrelectric", "milestone", "mr. handyman", "mr handyman",
    # healthcare / beauty / auto chains for the wider niche set
    "aspen dental", "western dental", "pacific dental", "gentle dental",
    "ideal image", "laseraway", "massage envy", "hand & stone", "european wax",
    "the joint chiropractic", "jiffy lube", "midas", "meineke", "firestone",
    "pep boys", "valvoline", "goodyear", "les schwab", "big o tires",
]

# Priority discount for franchises. Not zero: the lead stays in the list.
FRANCHISE_MULTIPLIER = 0.6


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
# Google returns the 5 most RELEVANT reviews, not the 5
# most recent, so this date is a lower bound: a recent review PROVES the
# business is trading, while an old one only fails to prove it. Confirmed-active
# therefore earns full activity points in scoring.fit_score, and an old sample
# only counts against a lead when nothing else (reviews, a live site) offsets it.
ACTIVITY_TIERS = [(90, "active"), (365, "steady"), (730, "quiet"), (99999, "stale")]
