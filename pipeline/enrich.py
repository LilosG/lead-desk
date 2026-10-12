"""
Enrichment — crawl the prospect's own public website and run PageSpeed Insights.

This is legitimate crawling: public pages, robots.txt respected, identified user
agent, rate limited, small page budget per site. We are not touching Google's
rendered pages.

What we're hunting for, in priority order:
  1. Reachability — an email or contact route. A perfect gap analysis on a
     business you can't contact is worth nothing.
  2. Local SEO gaps — schema, NAP, service/city pages. This is literally the
     Lilos service line, so these findings are the pitch.
  3. Performance — PSI mobile scores. Concrete, numeric, and undeniable.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse as urlparse
import urllib.robotparser as robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

import config as C


EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Phone matching must be FORMATTED, not a bare run of ten digits. The loose
# version matched tracking IDs, CSS values and script constants — it pulled
# '3333333333' and '6255304586' off real contractor sites and, combined with
# truncating the result list, produced false "your phone doesn't match Google"
# claims on 3 of 4 test leads. A separator or parens is required.
PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?"
    r"(?:\(\d{3}\)\s?|\d{3}[\s.\-])"
    r"\d{3}[\s.\-]\d{4}"
    r"(?!\d)"
)


def _plausible_phone(digits: str) -> bool:
    """Reject numbers that can't be real US local numbers."""
    if len(digits) != 10:
        return False
    if digits[0] in "01" or digits[3] in "01":      # invalid area/exchange
        return False
    if len(set(digits)) <= 2:                        # 3333333333, 1212121212
        return False
    if digits in {"1234567890", "0123456789"}:
        return False
    return True

# Emails that are never a real contact — tracking pixels, CDN noise, image files,
# example placeholders. Without this filter the emails_found column fills with junk
# and the outreach list looks fuller than it is.
EMAIL_JUNK = re.compile(
    r"(\.(png|jpg|jpeg|gif|svg|webp|css|js)$"
    r"|^(example|test|your|email|name|info)@(example|test|domain|email|yoursite)\."
    r"|sentry\.io$|wixpress\.com$|@2x\.|godaddy\.com$|squarespace\.com$)",
    re.I,
)

SOCIAL_DOMAINS = {
    "facebook.com": "facebook", "instagram.com": "instagram",
    "linkedin.com": "linkedin", "twitter.com": "twitter", "x.com": "twitter",
    "yelp.com": "yelp", "nextdoor.com": "nextdoor", "youtube.com": "youtube",
    "tiktok.com": "tiktok", "angi.com": "angi", "homeadvisor.com": "homeadvisor",
    "bbb.org": "bbb", "thumbtack.com": "thumbtack",
}

CMS_SIGNATURES = [
    ("wordpress", ["wp-content", "wp-includes", "wp-json"]),
    ("wix",       ["wix.com", "wixstatic", "_wixCssImports"]),
    ("squarespace", ["squarespace.com", "static1.squarespace"]),
    ("godaddy",   ["godaddysites.com", "img1.wsimg.com"]),
    ("duda",      ["dudamobile", "duda_website"]),
    ("weebly",    ["weebly.com", "editmysite.com"]),
    ("shopify",   ["cdn.shopify.com", "shopifycloud"]),
    ("webflow",   ["webflow.io", "assets.website-files.com"]),
    ("hubspot",   ["hs-scripts.com", "hubspot"]),
]
# Template builders are a *positive* buying signal for a website rebuild pitch:
# the owner already paid for a site, so they value having one, but these
# platforms cap out fast on local SEO. Easiest displacement in the list.
TEMPLATE_BUILDERS = {"wix", "squarespace", "godaddy", "weebly", "duda"}

import verticals as V

# Online booking / scheduling platforms. A booking widget is a real conversion
# path, so a site that has one must never be told it has "no way to contact".
BOOKING_PROVIDERS = {
    "calendly.com": "Calendly", "acuityscheduling.com": "Acuity",
    "squareup.com/appointments": "Square Appointments", "square.site/book": "Square Appointments",
    "vagaro.com": "Vagaro", "joinblvd.com": "Boulevard", "blvd.co": "Boulevard",
    "mindbodyonline.com": "Mindbody", "mindbody.io": "Mindbody",
    "zocdoc.com": "Zocdoc", "localmed.com": "LocalMed", "nexhealth.com": "NexHealth",
    "schedulicity.com": "Schedulicity", "glossgenius.com": "GlossGenius",
    "fresha.com": "Fresha", "booksy.com": "Booksy", "janeapp.com": "Jane",
    "housecallpro.com": "Housecall Pro", "getjobber.com": "Jobber",
    "servicetitan.com": "ServiceTitan", "opentable.com": "OpenTable",
    "resy.com": "Resy", "tock.com": "Tock", "setmore.com": "Setmore",
    "simplybook.me": "SimplyBook", "youcanbook.me": "YouCanBook.me",
    "tidycal.com": "TidyCal", "zenoti.com": "Zenoti", "aestheticrecord.com": "Aesthetic Record",
    "patientpop.com": "PatientPop", "weave.com/schedule": "Weave",
    "showingtime.com": "ShowingTime",
}

# Pages that exist on nearly every site and say nothing about offerings.
GENERIC_PATH_WORDS = (
    "blog", "post", "news", "tag", "category", "author", "privacy", "terms",
    "about", "contact", "career", "job", "faq", "review", "testimonial",
    "gallery", "login", "cart", "account", "feed", "wp-", "sitemap", "page/",
)

SITEMAP_MAX_URLS = 2000


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _offering_words(business: dict) -> list[str]:
    return list(V.niche_profile(business.get("vertical"))["offering_words"])


def _location_tokens(business: dict) -> list[str]:
    tokens = set(C.LOCATION_PAGE_WORDS)
    for raw in (business.get("city"), (business.get("market") or "").split(",")[0]):
        slug = _slug(raw)
        if len(slug) >= 3:
            tokens.add(slug)
    return sorted(tokens)


def _path_matches(path: str, words: list[str]) -> bool:
    return any(w in path for w in words)


def _anchor_title(text: str) -> str | None:
    """A short, human link label usable as an offering name in a mockup."""
    t = " ".join((text or "").split())
    if not t or len(t) > 40 or len(t.split()) > 6:
        return None
    low = t.lower()
    if low in {"services", "our services", "all services", "learn more", "read more",
               "view all", "home", "menu", "more"}:
        return None
    return t


@dataclass
class SiteFindings:
    place_id: str = ""
    resolved_url: str | None = None
    http_status: int | None = None
    is_reachable: bool = False
    has_ssl: bool = False
    redirects_to: str | None = None

    title: str | None = None
    title_length: int | None = None
    meta_description: str | None = None
    meta_desc_length: int | None = None
    h1_text: str | None = None
    h1_count: int = 0
    word_count: int = 0
    page_count_estimate: int = 0

    has_localbusiness_schema: bool = False
    schema_types: list = field(default_factory=list)
    nap_phone_on_site: str | None = None
    nap_address_on_site: str | None = None
    nap_matches_gbp: bool | None = None
    has_service_pages: bool = False       # "offering pages" in niche terms
    has_city_pages: bool = False          # "location pages" in niche terms
    has_gbp_link: bool = False
    offering_page_count: int = 0
    offering_titles: list = field(default_factory=list)
    location_page_count: int = 0
    sitemap_url_count: int | None = None
    has_online_booking: bool = False
    booking_provider: str | None = None

    has_contact_form: bool = False
    contact_page_url: str | None = None
    emails_found: list = field(default_factory=list)
    phones_found: list = field(default_factory=list)
    social_profiles: dict = field(default_factory=dict)

    cms_detected: str | None = None
    is_template_builder: bool = False

    psi_performance: int | None = None
    psi_seo: int | None = None
    psi_accessibility: int | None = None
    psi_best_practices: int | None = None
    psi_lcp_ms: int | None = None
    psi_cls: float | None = None
    psi_mobile_friendly: bool | None = None

    crawl_error: str | None = None
    # "gbp": the site linked on the Google profile. "found": no site on the
    # profile, but we found and verified the business's own site by name.
    site_source: str = "gbp"
    raw_psi_payload: dict | None = None


def _norm_phone(p: str | None) -> str:
    return re.sub(r"\D", "", p or "")[-10:]


def _robots_ok(base: str, url: str, cache: dict) -> bool:
    if not C.RESPECT_ROBOTS:
        return True
    if base not in cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(urlparse.urljoin(base, "/robots.txt"))
        try:
            # RobotFileParser.read() calls urllib.request.urlopen with NO
            # timeout, so a stalled server hangs this worker forever. Observed
            # on the plumber sweep: crawl workers parked in _robots_ok for
            # minutes with the batch unable to finish. Fetch it ourselves with
            # the normal crawl timeout and hand the lines to the parser.
            rr = requests.get(
                urlparse.urljoin(base, "/robots.txt"),
                headers={"User-Agent": C.USER_AGENT},
                timeout=C.CRAWL_TIMEOUT_S,
            )
            if rr.status_code >= 400:
                raise OSError(f"robots status {rr.status_code}")
            rp.parse(rr.text.splitlines())
        except Exception:
            # No reachable robots.txt means no stated restriction. Proceed, but
            # our page budget and delay still apply.
            rp = None
        cache[base] = rp
    rp = cache[base]
    if rp is None:
        return True
    try:
        return rp.can_fetch(C.USER_AGENT, url)
    except Exception:
        return True


# Statuses that mean "a bot filter turned us away," NOT "this site is broken."
# Treating these as downtime produced false claims in testing: 2 of 3 sites
# flagged as dead were actually healthy and just fronted by a WAF. Telling a
# prospect their site is down when it isn't destroys the pitch on contact.
BOT_BLOCK_STATUSES = {401, 403, 406, 409, 429, 999}

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _fetch(session, url: str, _retry: bool = True) -> requests.Response | None:
    """Fetch politely, with one fallback attempt.

    First attempt identifies us honestly. If a bot filter rejects it, we retry
    once with a standard browser UA — we're requesting the same public page a
    visitor sees, at one request per second, with robots.txt still enforced.
    Transient 5xx also gets one retry, because a single blip shouldn't get a
    business labelled as having a dead website.
    """
    def _get(ua):
        return session.get(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=C.CRAWL_TIMEOUT_S,
            allow_redirects=True,
        )

    try:
        r = _get(C.USER_AGENT)
    except Exception:
        if not _retry:
            return None
        time.sleep(1.5)
        try:
            r = _get(BROWSER_UA)
        except Exception:
            return None

    if _retry and r is not None:
        if r.status_code in BOT_BLOCK_STATUSES:
            time.sleep(1.0)
            try:
                r2 = _get(BROWSER_UA)
                if r2.status_code < 400:
                    return r2
                # Still refused — mark it so scoring can distinguish a blocked
                # site from a dead one.
                r2.lilos_blocked = True  # type: ignore[attr-defined]
                return r2
            except Exception:
                r.lilos_blocked = True  # type: ignore[attr-defined]
                return r
        if 500 <= r.status_code < 600:
            time.sleep(2.0)
            try:
                r2 = _get(BROWSER_UA)
                if r2.status_code < 400:
                    return r2
                return r2
            except Exception:
                return r
    return r


# schema.org LocalBusiness and its subtypes, lower-cased. Any of these counts as
# business markup. The old list only knew trades, so a dentist marked up as
# "Dentist" was told it had no business markup at all.
LOCAL_BUSINESS_TYPES = {t.lower() for t in """
LocalBusiness
AnimalShelter ArchiveOrganization AutomotiveBusiness AutoBodyShop AutoDealer
AutoPartsStore AutoRental AutoRepair AutoWash GasStation MotorcycleDealer
MotorcycleRepair ChildCare Dentist DryCleaningOrLaundry EmergencyService
FireStation Hospital PoliceStation EmploymentAgency EntertainmentBusiness
AdultEntertainment AmusementPark ArtGallery Casino ComedyClub MovieTheater
NightClub FinancialService AccountingService AutomatedTeller BankOrCreditUnion
InsuranceAgency FoodEstablishment Bakery BarOrPub Brewery CafeOrCoffeeShop
Distillery FastFoodRestaurant IceCreamShop Restaurant Winery GovernmentOffice
PostOffice HealthAndBeautyBusiness BeautySalon DaySpa HairSalon HealthClub
NailSalon TattooParlor HomeAndConstructionBusiness Electrician GeneralContractor
HVACBusiness HousePainter Locksmith MovingCompany Plumber RoofingContractor
InternetCafe LegalService Attorney Notary Library LodgingBusiness
BedAndBreakfast Campground Hostel Hotel Motel Resort VacationRental
MedicalBusiness CommunityHealth Dermatology DietNutrition Geriatric
Gynecologic MedicalClinic CovidTestingFacility Midwifery Nursing Obstetric
Oncologic Optician Optometric Otolaryngologic Pediatric Pharmacy Physician
IndividualPhysician PhysiciansOffice Physiotherapy PlasticSurgery Podiatric
PrimaryCare Psychiatric PublicHealth RadioStation RealEstateAgent RecyclingCenter
SelfStorage ShoppingCenter SportsActivityLocation BowlingAlley ExerciseGym
GolfCourse PublicSwimmingPool SkiResort SportsClub StadiumOrArena TennisComplex
Store BikeStore BookStore ClothingStore ComputerStore ConvenienceStore
DepartmentStore ElectronicsStore Florist FurnitureStore GardenStore GroceryStore
HardwareStore HobbyShop HomeGoodsStore JewelryStore LiquorStore MensClothingStore
MobilePhoneStore MovieRentalStore MusicStore OfficeEquipmentStore OutletStore
PawnShop PetStore ShoeStore SportingGoodsStore TireShop ToyStore WholesaleStore
TelevisionStation TouristInformationCenter TravelAgency ProfessionalService
MedicalOrganization Contractor HomeAndConstructionBusiness
""".split()}


def _extract_schema(soup: BeautifulSoup) -> tuple[bool, list]:
    types: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            nodes = graph if isinstance(graph, list) else [node]
            for n in nodes:
                if isinstance(n, dict) and n.get("@type"):
                    t = n["@type"]
                    types.extend(t if isinstance(t, list) else [t])
    # LocalBusiness has many subtypes (Electrician, Plumber, HVACBusiness...) and
    # any of them counts as correctly marked up.
    has_local = any(str(t).lower().rsplit("/", 1)[-1] in LOCAL_BUSINESS_TYPES for t in types)
    return has_local, sorted(set(str(t) for t in types))


FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "me.com", "comcast.net", "sbcglobal.net", "att.net",
    "verizon.net", "msn.com", "live.com", "cox.net", "protonmail.com",
}


def _registrable(host: str) -> str:
    """Crude eTLD+1. Good enough to compare a site to the emails on it."""
    parts = (host or "").lower().replace("www.", "").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _clean_emails(raw: set, site_host: str = "") -> list:
    """Keep only addresses plausibly belonging to THIS business.

    The trap this closes: contractor sites routinely carry a 'site by <agency>'
    footer credit with the developer's address. Scraping that and pitching the
    business owner means emailing a stranger about a company they don't own —
    caught exactly this in testing (micah@micahrich.com harvested off DJB
    Electric's site).

    Rule: accept the address if its domain matches the website's domain, or if
    it's a consumer mailbox (plenty of real contractors run on gmail). Reject
    any OTHER custom domain — that's someone else's business.
    """
    site_domain = _registrable(site_host)
    out, rejected = [], []
    for e in raw:
        e = e.strip().lower().rstrip(".,;:)")
        if EMAIL_JUNK.search(e) or len(e) > 80 or "@" not in e:
            continue
        edomain = _registrable(e.split("@")[-1])
        if site_domain and edomain != site_domain and edomain not in FREE_MAIL_DOMAINS:
            rejected.append(e)
            continue
        out.append(e)
    # Prefer role addresses a business actually monitors over scraped noise.
    priority = ("info@", "contact@", "office@", "sales@", "hello@", "service@", "admin@")
    out = sorted(set(out), key=lambda e: (not e.startswith(priority), e))
    return out[:5]


def _root_url(url: str) -> str | None:
    parsed = urlparse.urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def _sitemap_paths(session, base: str, robots_cache: dict) -> list[str] | None:
    """Paths listed in /sitemap.xml (following one index level). None if absent."""
    def _locs(xml: str) -> list[str]:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "", re.I)

    url = urlparse.urljoin(base, "/sitemap.xml")
    if not _robots_ok(base, url, robots_cache):
        return None
    r = _fetch(session, url, _retry=False)
    if r is None or r.status_code >= 400 or "<loc>" not in (r.text or "").lower():
        r = _fetch(session, urlparse.urljoin(base, "/sitemap_index.xml"), _retry=False)
        if r is None or r.status_code >= 400 or "<loc>" not in (r.text or "").lower():
            return None
    locs = _locs(r.text)
    if "<sitemapindex" in (r.text or "").lower():
        children = [u for u in locs if not re.search(r"(post|blog|tag|category|author|product)", u, re.I)]
        locs = []
        for child in children[:3]:
            time.sleep(C.CRAWL_DELAY_S)
            rc = _fetch(session, child, _retry=False)
            if rc is not None and rc.status_code < 400:
                locs.extend(_locs(rc.text))
            if len(locs) >= SITEMAP_MAX_URLS:
                break
    host = urlparse.urlparse(base).netloc.replace("www.", "")
    paths = []
    for u in locs[:SITEMAP_MAX_URLS]:
        parsed = urlparse.urlparse(u)
        if parsed.netloc.replace("www.", "") == host:
            paths.append(parsed.path.lower())
    return paths


def crawl_site(business: dict, session: requests.Session | None = None) -> SiteFindings:
    """Crawl one prospect site. Never raises — failures land in crawl_error."""
    f = SiteFindings(place_id=business["place_id"])
    url = business.get("website_url")
    if not url:
        f.crawl_error = "no_website"
        return f

    session = session or requests.Session()
    robots_cache: dict = {}

    resp = _fetch(session, url)
    if resp is None:
        f.crawl_error = "unreachable"
        return f

    f.http_status = resp.status_code
    f.resolved_url = resp.url
    f.has_ssl = resp.url.startswith("https://")
    f.is_reachable = resp.status_code < 400
    if resp.url.rstrip("/") != url.rstrip("/"):
        f.redirects_to = resp.url
    if not f.is_reachable:
        # Separate "we were blocked" from "the site is broken". Only the second
        # is a finding we can put in front of a prospect.
        if getattr(resp, "lilos_blocked", False) or resp.status_code in BOT_BLOCK_STATUSES:
            f.crawl_error = f"blocked_{resp.status_code}"
            return f
        # The Google profile often links a deep URL (a /locations page, a
        # tracking query, a stray "//"). If THAT fails but the homepage loads,
        # the site isn't down: the profile's link is broken. Different finding,
        # and saying "your site is down" would be false.
        root = _root_url(url)
        if root and root.rstrip("/") != url.rstrip("/"):
            r_root = _fetch(session, root)
            if r_root is not None and r_root.status_code < 400:
                f.crawl_error = f"profile_link_{resp.status_code}"
                f.redirects_to = r_root.url
                return f
        f.crawl_error = f"http_{resp.status_code}"
        return f

    parsed = urlparse.urlparse(resp.url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")

    # --- homepage SEO fundamentals ---
    if soup.title and soup.title.string:
        f.title = soup.title.string.strip()[:300]
        f.title_length = len(f.title)
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if md and md.get("content"):
        f.meta_description = md["content"].strip()[:500]
        f.meta_desc_length = len(f.meta_description)
    h1s = soup.find_all("h1")
    f.h1_count = len(h1s)
    if h1s:
        f.h1_text = h1s[0].get_text(strip=True)[:300]
    f.word_count = len(soup.get_text(" ", strip=True).split())

    f.has_localbusiness_schema, f.schema_types = _extract_schema(soup)

    low_html = html.lower()
    for cms, sigs in CMS_SIGNATURES:
        if any(s.lower() in low_html for s in sigs):
            f.cms_detected = cms
            break
    f.is_template_builder = f.cms_detected in TEMPLATE_BUILDERS

    emails: set = set(EMAIL_RE.findall(html))
    phones: set = set(PHONE_RE.findall(html))

    # mailto:/tel: are higher-confidence than body-text regex hits
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            emails.add(urlparse.unquote(href[7:].split("?")[0]))
        elif low.startswith("tel:"):
            phones.add(href[4:])
        else:
            for dom, key in SOCIAL_DOMAINS.items():
                if dom in low and key not in f.social_profiles:
                    f.social_profiles[key] = href if href.startswith("http") else base + href
            if "google.com/maps" in low or "g.page" in low or "goo.gl/maps" in low:
                f.has_gbp_link = True

    # --- booking platforms (links, iframes, scripts) ---
    for host, provider in BOOKING_PROVIDERS.items():
        if host in low_html:
            f.has_online_booking = True
            f.booking_provider = provider
            break

    # --- follow a small set of internal pages ---
    offering_words = _offering_words(business)
    location_tokens = _location_tokens(business)
    offering_paths: set[str] = set()
    location_paths: set[str] = set()
    internal: list[str] = []
    seen = {resp.url.rstrip("/")}
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urlparse.urljoin(base, href)
        if urlparse.urlparse(full).netloc != parsed.netloc:
            continue
        path = urlparse.urlparse(full).path.lower()
        anchor = a.get_text(" ", strip=True)
        anchor_slug = _slug(anchor)
        if path not in ("", "/") and (
            _path_matches(path, offering_words) or _path_matches(anchor_slug, offering_words)
        ):
            offering_paths.add(path.rstrip("/"))
            title = _anchor_title(anchor)
            if title and title not in f.offering_titles and len(f.offering_titles) < 8:
                f.offering_titles.append(title)
        if path not in ("", "/") and _path_matches(path, location_tokens):
            location_paths.add(path.rstrip("/"))
        if full.rstrip("/") in seen:
            continue
        if any(h in path for h in C.CONTACT_PAGE_HINTS):
            internal.append(full)
            seen.add(full.rstrip("/"))
        f.page_count_estimate += 1

    for link in internal[: C.CRAWL_MAX_PAGES - 1]:
        if not _robots_ok(base, link, robots_cache):
            continue
        time.sleep(C.CRAWL_DELAY_S)
        r2 = _fetch(session, link)
        if not r2 or r2.status_code >= 400:
            continue
        h2 = r2.text or ""
        s2 = BeautifulSoup(h2, "html.parser")
        emails |= set(EMAIL_RE.findall(h2))
        phones |= set(PHONE_RE.findall(h2))
        for a in s2.find_all("a", href=True):
            if a["href"].lower().startswith("mailto:"):
                emails.add(urlparse.unquote(a["href"][7:].split("?")[0]))
        if s2.find("form") and f.contact_page_url is None:
            f.has_contact_form = True
            f.contact_page_url = r2.url
        if not f.has_localbusiness_schema:
            got, types = _extract_schema(s2)
            if got:
                f.has_localbusiness_schema = True
                f.schema_types = sorted(set(f.schema_types + types))

    # --- sitemap: catches offering/location pages the homepage never links ---
    sitemap_paths = _sitemap_paths(session, base, robots_cache)
    if sitemap_paths is not None:
        f.sitemap_url_count = len(sitemap_paths)
        content_pages = 0
        for path in sitemap_paths:
            if path in ("", "/"):
                continue
            if _path_matches(path, offering_words):
                offering_paths.add(path.rstrip("/"))
            if _path_matches(path, location_tokens):
                location_paths.add(path.rstrip("/"))
            if not any(g in path for g in GENERIC_PATH_WORDS):
                content_pages += 1
        # A site with many substantive pages almost certainly covers its
        # offerings even when the slugs don't use our vocabulary. Stay quiet.
        if not offering_paths and content_pages >= 6:
            f.offering_page_count = content_pages
            f.has_service_pages = True

    if offering_paths:
        f.offering_page_count = max(f.offering_page_count, len(offering_paths))
        f.has_service_pages = True
    f.location_page_count = len(location_paths)
    f.has_city_pages = bool(location_paths)

    if not f.has_contact_form:
        # Detect ANY real form, then exclude search boxes — the previous
        # input-name heuristic was too strict and reported "no contact form" on
        # a site that plainly had one, which is a false claim we'd have emailed.
        # Bias toward assuming a form exists; a missed opportunity beats a lie.
        for form in soup.find_all("form"):
            action = (form.get("action") or "").lower()
            role = (form.get("role") or "").lower()
            cls = " ".join(form.get("class") or []).lower()
            is_search = (
                role == "search" or "search" in action or "search" in cls
                or form.find("input", attrs={"type": "search"}) is not None
            )
            if is_search:
                continue
            if form.find_all(["input", "textarea", "select"]):
                f.has_contact_form = True
                f.contact_page_url = resp.url
                break
        # Third-party embedded forms render in an iframe, so there's no <form>
        # in our HTML at all.
        if not f.has_contact_form:
            for iframe in soup.find_all("iframe"):
                src = (iframe.get("src") or "").lower()
                if any(k in src for k in ("jotform", "hubspot", "typeform",
                                          "wufoo", "gravityforms", "formstack",
                                          "docs.google.com/forms", "calendly")):
                    f.has_contact_form = True
                    f.contact_page_url = resp.url
                    break

    f.emails_found = _clean_emails(emails, parsed.netloc)

    all_phones = {d for d in (_norm_phone(p) for p in phones) if _plausible_phone(d)}

    # --- NAP consistency against the GBP record ---
    # Compare against the COMPLETE set before truncating for storage. Checking
    # the truncated list was the actual source of the false mismatches: the real
    # number was present on the page but sorted out of the stored top-5.
    gbp_phone = _norm_phone(business.get("phone"))
    if gbp_phone and all_phones:
        f.nap_matches_gbp = gbp_phone in all_phones
        f.nap_phone_on_site = sorted(all_phones)[0]
    elif gbp_phone:
        # No phone found anywhere on the site. That's "couldn't verify", not
        # "mismatch" — plenty of sites render the number inside an image or via
        # JS. Leaving it None keeps us from asserting something we didn't check.
        f.nap_matches_gbp = None

    f.phones_found = sorted(all_phones)[:8]

    return f


# ---------------------------------------------------------------------------
# PageSpeed Insights
# ---------------------------------------------------------------------------
def run_psi(url: str, api_key: str, strategy: str = "mobile") -> dict | None:
    """PSI is free but slow (10-30s/site) and rate limited to roughly 4 QPS."""
    params = {
        "url": url,
        "strategy": strategy,
        "category": ["performance", "seo", "accessibility", "best-practices"],
    }
    if api_key:
        params["key"] = api_key
    try:
        r = requests.get(C.PSI_URL, params=params, timeout=90)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def apply_psi(f: SiteFindings, payload: dict | None) -> SiteFindings:
    if not payload:
        return f
    lh = payload.get("lighthouseResult") or {}
    cats = lh.get("categories") or {}

    def score(key):
        c = cats.get(key) or {}
        v = c.get("score")
        return int(round(v * 100)) if isinstance(v, (int, float)) else None

    f.psi_performance    = score("performance")
    f.psi_seo            = score("seo")
    f.psi_accessibility  = score("accessibility")
    f.psi_best_practices = score("best-practices")

    audits = lh.get("audits") or {}
    lcp = (audits.get("largest-contentful-paint") or {}).get("numericValue")
    cls = (audits.get("cumulative-layout-shift") or {}).get("numericValue")
    f.psi_lcp_ms = int(lcp) if isinstance(lcp, (int, float)) else None
    f.psi_cls    = round(cls, 3) if isinstance(cls, (int, float)) else None
    if f.psi_performance is not None:
        f.psi_mobile_friendly = f.psi_performance >= 50

    # Store trimmed payload — the full Lighthouse blob is ~500KB and would bloat
    # the database for no analytical gain.
    f.raw_psi_payload = {
        "categories": {k: (cats.get(k) or {}).get("score") for k in cats},
        "fetchTime": lh.get("fetchTime"),
        "finalUrl": lh.get("finalUrl"),
    }
    # Google's own phone-sized render of the homepage (a ~20-60KB JPEG data
    # URI). The audit report shows it next to the speed score.
    shot = ((audits.get("final-screenshot") or {}).get("details") or {}).get("data")
    if isinstance(shot, str) and shot.startswith("data:image/") and len(shot) < 400_000:
        f.raw_psi_payload["screenshot"] = shot
    return f


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------
def enrich_all(
    businesses: list, with_psi: bool = True, max_workers: int | None = None,
    psi_limit: int | None = None, progress=print,
) -> dict:
    """Crawl every business with a website; optionally run PSI on the top slice.

    PSI is the slow, rate-limited step, so it's separated: crawl everything,
    then spend the PSI budget only where it changes a decision.
    """
    max_workers = max_workers or C.CRAWL_MAX_CONCURRENT
    results: dict = {}
    have_site = [b for b in businesses if b.get("website_url")]
    no_site = [b for b in businesses if not b.get("website_url")]

    progress(f"{len(no_site)} businesses with no website on Google; checking for an unlisted site...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for b, f in zip(no_site, ex.map(crawl_unlisted, no_site)):
            results[b["place_id"]] = f
    found = [b for b in no_site if results[b["place_id"]].site_source == "found"]
    progress(f"  found {len(found)} real site(s) that aren't linked on Google")
    progress(f"crawling {len(have_site)} sites...")

    session_pool = [requests.Session() for _ in range(max_workers)]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(crawl_site, b, session_pool[i % max_workers]): b
            for i, b in enumerate(have_site)
        }
        done = 0
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                results[b["place_id"]] = fut.result()
            except Exception as e:
                results[b["place_id"]] = SiteFindings(
                    place_id=b["place_id"], crawl_error=f"exception: {e}"[:200]
                )
            done += 1
            if done % 25 == 0:
                progress(f"  crawled {done}/{len(have_site)}")

    if with_psi:
        targets = [b for b in have_site + found if results[b["place_id"]].is_reachable]
        if psi_limit:
            targets = targets[:psi_limit]
        progress(f"running PageSpeed on {len(targets)} reachable sites (slow)...")
        # 3 workers keeps us under PSI's ~4 QPS ceiling with headroom.
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {
                ex.submit(run_psi, results[b["place_id"]].resolved_url or b["website_url"],
                          C.GOOGLE_API_KEY): b
                for b in targets
            }
            done = 0
            for fut in as_completed(futs):
                b = futs[fut]
                try:
                    apply_psi(results[b["place_id"]], fut.result())
                except Exception:
                    pass
                done += 1
                if done % 10 == 0:
                    progress(f"  psi {done}/{len(targets)}")

    return results


# ---------------------------------------------------------------------------
# Sites that exist but aren't on the Google profile
# ---------------------------------------------------------------------------
# Google's listing is often missing the website even though the business has
# one. Calling that "no website" is a false claim, so before we conclude it, we
# try the obvious domains built from the business name and accept one only if
# the page carries the profile's phone number, or the business name AND city.
_LEGAL_WORDS = {"inc", "llc", "co", "corp", "corporation", "ltd", "pllc", "pc", "the"}
_PARKED_HINTS = ("domain is for sale", "buy this domain", "domain may be for sale",
                 "this domain is parked", "parked free", "godaddy.com/domainsearch",
                 "hugedomains", "sedo.com", "dan.com")
FINDER_TIMEOUT_S = 6


def _name_tokens(name: str | None) -> list[str]:
    text = (name or "").lower()
    text = re.split(r"\s+[|•·]\s+|\s+[-–—]\s+", text)[0]
    text = text.replace("&", " and ").replace("+", " and ")
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if t not in _LEGAL_WORDS]


# Words businesses tack onto their name in the domain ("aaagoforthplumbing"
# + "anddrainservice"). Only tried after the plain name; DNS filters the rest.
_COMMON_SUFFIXES = ["services", "service", "co", "inc", "llc", "company", "group", "pros"]
_NICHE_SUFFIXES = {
    "home_service": ["anddrain", "anddrainservice", "anddrainservices", "anddrainage",
                     "androoter", "andheating", "andair", "andcooling", "andsons",
                     "contractor", "contractors"],
    "medical_aesthetic": ["medspa", "spa", "clinic", "aesthetics", "skincare"],
    "dental": ["dental", "dentistry", "dds", "smiles"],
    "legal": ["law", "lawfirm", "lawgroup", "lawyers", "attorneys"],
    "real_estate": ["realestate", "realty", "homes", "properties"],
    "wellness_health": ["chiropractic", "clinic", "wellness", "therapy"],
    "auto": ["auto", "autorepair", "automotive"],
}


def candidate_domains(business: dict, limit: int = 40) -> list[str]:
    """Likely domains for a business name, most likely first.

    'AAA Goforth Plumbing' -> aaagoforthplumbing.com, ..., then the same name
    with common and trade suffixes (aaagoforthplumbinganddrainservice.com).
    """
    tokens = _name_tokens(business.get("name"))
    if not tokens:
        return []
    city = re.sub(r"[^a-z0-9]", "", (business.get("city") or "").lower())
    no_and = [t for t in tokens if t != "and"]
    variants = [tokens, no_and]
    and_positions = [i for i, t in enumerate(tokens) if t == "and"]
    if len(and_positions) > 1:
        for i in and_positions:
            variants.append(tokens[:i] + tokens[i + 1:])
    if city:
        variants.append(no_and + [city])
    stems: list[str] = []
    for v in variants:
        stem = "".join(v)
        if 4 <= len(stem) <= 63 and stem not in stems:
            stems.append(stem)
    if not stems:
        return []
    base = stems[0]
    profile = V.vertical_profile(business.get("vertical") or "")
    suffixes = _NICHE_SUFFIXES.get(profile, []) + _COMMON_SUFFIXES
    for suffix in suffixes:
        for stem in dict.fromkeys([base, "".join(no_and)]):
            cand = stem + suffix
            if not stem.endswith(suffix) and len(cand) <= 63 and cand not in stems:
                stems.append(cand)
    out = [stem + ".com" for stem in stems]
    out.insert(len(variants), base + ".net")
    return list(dict.fromkeys(out))[:limit]


def _resolves(domain: str) -> bool:
    import socket
    try:
        socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, UnicodeError, OSError):
        return False


def _digits(text: str) -> str:
    d = re.sub(r"\D", "", text or "")
    return d[-10:] if len(d) >= 10 else d


def _verifies(business: dict, html: str) -> bool:
    low = html.lower()
    if any(h in low for h in _PARKED_HINTS):
        return False
    phone = _digits(business.get("phone") or "")
    if len(phone) == 10:
        found = {_digits(m) for m in PHONE_RE.findall(html)}
        if phone in found:
            return True
        if phone in re.sub(r"\D", "", low):
            return True
    city = (business.get("city") or "").lower().strip()
    distinctive = [t for t in _name_tokens(business.get("name"))
                   if len(t) >= 4 and t not in {"and", "plumbing", "service", "services",
                                                "electric", "electrical", "dental", "spa"}]
    hits = sum(1 for t in distinctive if t in low)
    return bool(city) and city in low and distinctive and hits >= min(2, len(distinctive))


def find_unlisted_site(business: dict, session: requests.Session | None = None) -> str | None:
    """The business's own website when Google's profile has none, or None."""
    session = session or requests.Session()
    candidates = candidate_domains(business)
    # DNS first, in parallel: most guesses don't exist and cost nothing to rule out.
    with ThreadPoolExecutor(max_workers=8) as ex:
        live = [d for d, ok in zip(candidates, ex.map(
            lambda d: _resolves(d.split(":")[0]) or ":" in d, candidates)) if ok]
    for domain in live:
        for url in (f"https://www.{domain}/", f"http://{domain}/"):
            try:
                r = session.get(url, timeout=FINDER_TIMEOUT_S, allow_redirects=True,
                                headers={"User-Agent": C.USER_AGENT})
            except requests.RequestException:
                continue
            if r.status_code < 400 and "html" in (r.headers.get("Content-Type") or "html"):
                if _verifies(business, r.text or ""):
                    return r.url
                break  # domain answered but isn't this business: next domain
    return None


def crawl_unlisted(business: dict, session: requests.Session | None = None) -> SiteFindings:
    """For a profile with no website: find the real site and crawl it, or say none."""
    session = session or requests.Session()
    url = find_unlisted_site(business, session)
    if not url:
        return SiteFindings(place_id=business["place_id"], crawl_error="no_website")
    f = crawl_site({**business, "website_url": url}, session)
    f.site_source = "found"
    return f
