"""Depth checks behind the audit: site structure, on-page basics, AI search access.

`collect()` turns a crawled homepage into a plain dict stored on
website_enrichment.site_signals. `findings()` turns that dict into evidence.
Sweeps and audit reports share both, so a lead never gets two different answers.

Rule for every check: claim a gap only on positive evidence. If we couldn't look
(no sitemap, no robots.txt, a page failed to load), the check is left unknown
and nothing is said. A missed finding costs nothing; a false one costs the pitch.

On AI search, the wording stays inside what's established. Google's guidance
(May 2026) is that AI Overviews run on normal search fundamentals: no special
schema, no llms.txt. So these are access and clarity checks, never a promise of
being mentioned, and llms.txt is deliberately not scored.
"""
from __future__ import annotations

import functools
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

SIGNALS_VERSION = 1
MAX_SAMPLED_PAGES = 6
THIN_PAGE_WORDS = 200

# Crawlers that fetch pages to answer searches. Training crawlers (GPTBot,
# ClaudeBot, Google-Extended) are left out on purpose: blocking those is a
# legitimate choice and doesn't keep a business out of AI answers.
AI_SEARCH_BOTS = {
    "OAI-SearchBot": "ChatGPT search",
    "PerplexityBot": "Perplexity",
    "Claude-SearchBot": "Claude search",
    "bingbot": "Bing and Copilot",
    "Googlebot": "Google, including AI Overviews",
}

ANALYTICS_MARKERS = {
    "Google Analytics": ("google-analytics.com", "gtag(", "googletagmanager.com/gtag"),
    "Google Tag Manager": ("googletagmanager.com/gtm",),
    "Meta Pixel": ("connect.facebook.net",),
    "CallRail": ("callrail.com",),
    "Hotjar": ("hotjar.com",),
    "Microsoft Clarity": ("clarity.ms",),
}

# Every signal findings() can emit.
SIGNALS = frozenset({
    "noindex_homepage", "ai_crawlers_blocked", "js_only_content", "title_missing_location",
    "no_service_city_pages", "homepage_unclear", "no_click_to_call", "no_faq_content",
    "no_service_schema", "no_schema_profile_links", "no_analytics", "images_missing_alt",
    "thin_service_pages", "service_pages_missing_location",
})

_PHONE_TEXT = re.compile(r"\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
_JS_APP_ROOTS = ("root", "app", "__next", "__nuxt", "___gatsby")
# Keep in step with EV_SERVICE_PATTERN in app/campaigns.py.
EV_SERVICE = re.compile(
    r"\belectric\s+(vehicle|car)s?\b"
    r"|\b(evs?|tesla)\b.{0,30}(charg|install|outlet|ready|circuit|wiring)"
    r"|\bcharg.{0,30}\bevs?\b"
    r"|\b(car|vehicle)[\s-]+charg"
    r"|\bcharging\s+stations?\b"
    r"|\blevel[\s-]*2\s+(home\s+)?charg"
    r"|\bwall\s+connector\b"
    r"|\bevse\b",
    re.I,
)
# The four Permit Packets job types, in display order. Keep in step with
# PERMIT_JOBS in app/campaigns.py (a test compares them). ev_charger is EV_SERVICE.
PERMIT_JOB_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ev_charger", EV_SERVICE.pattern),
    ("service_upgrade",
     r"(?<!solar\s)\b(breaker\s+box|(electrical\s+|breaker\s+)?panel)s?\s+(upgrad|replac|chang)\w*"
     r"|\belectrical\s+service\s+(upgrad|chang|replac)\w*"
     r"|\b(upgrad|chang)\w*\s+(your|the)\s+electrical\s+service\b"
     r"|\b(100|125|150|200|400)[\s-]*amps?\s+(electrical\s+)?(service|panel)"),
    ("subpanel",
     r"\bsub[\s-]?panels?\b"
     r"|\bdetached\s+(garage|building|workshop)s?\b.{0,40}(power|wiring|feeder|electric)"
     r"|\b(power|wiring|feeder|electric)\w*\b.{0,40}\bdetached\s+(garage|building|workshop)"
     r"|\badus?\b.{0,40}(electric|wiring|panel)"
     r"|\b(electric|wiring|panel)\w*\b.{0,40}\badus?\b"),
    ("appliance_circuit",
     r"\b(hot\s*tub|spa|jacuzzi|swim\s+spa)s?\b.{0,40}(wiring|install|circuit|power)"
     r"|\b(wiring|install|circuit|power)\w*\b.{0,40}\b(hot\s*tub|spa|jacuzzi|swim\s+spa)s?\b"
     r"|\bsaunas?\b"
     r"|\bheat\s+pumps?\b.{0,40}(wiring|circuit|install)"
     r"|\b(wiring|circuit|install)\w*\b.{0,40}\bheat\s+pumps?\b"
     r"|\b(mini[\s-]*splits?|ductless)\b.{0,40}(install|wiring|circuit|electrical|hook[\s-]?up)"
     r"|\b(install|wiring|circuit|electrical|hook[\s-]?up)\w*\b.{0,40}\b(mini[\s-]*splits?|ductless)\b"
     r"|\b(240|220)[\s-]*(v|volts?)\b[\s-]*(circuit|outlet|line)"),
)
PERMIT_JOB_REGEX = {slug: re.compile(pattern, re.I) for slug, pattern in PERMIT_JOB_PATTERNS}
_FAQ_HEADING = re.compile(r"\b(faqs?|frequently asked|common questions|questions)\b", re.I)
# Parent folders that hold one page per town or neighborhood.
_AREA_PARENTS = {"service-area", "service-areas", "areas", "areas-we-serve", "areas-served",
                 "locations", "location", "cities", "communities", "neighborhoods"}
# Niches where a page per service in each town is a normal way to compete.
SERVICE_CITY_PROFILES = {"home_service", "legal", "auto", "wellness_health", "medical_aesthetic", "dental"}


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


EV_BRANDS = {
    "Tesla": r"\btesla\b",
    "ChargePoint": r"\bcharge\s?point\b",
    "JuiceBox": r"\bjuice\s?box\b",
    "Wallbox": r"\bwallbox\b",
    "Emporia": r"\bemporia\b",
    "Grizzl-E": r"\bgrizzl-?e\b",
    "ClipperCreek": r"\bclipper\s?creek\b",
}
_EV_COMMERCIAL = re.compile(
    r"\bcommercial\b.{0,60}\b(ev|charging|charger)|\b(ev|charging|charger)\b.{0,60}\bcommercial\b"
    r"|\b(fleet|workplace|parking lot)\b.{0,40}charg",
    re.I,
)
# A blog post, tip sheet or guide shows interest. A service page shows they sell it.
_EDITORIAL_PATH = re.compile(r"/(blog|news|posts?|articles?|tag|category|resources|expert-tips|tips|learn|guides|faq|how-to)(/|$)", re.I)
# Any page that could list what they do: /electric-c10/residential-services, /what-we-do.
_SERVICE_HUB = re.compile(r"service|residential|electric|what[-_]we[-_]do", re.I)
MAX_EV_PAGE_FETCHES = 4


def _hub_rank(path: str) -> tuple[bool, bool, int]:
    low = path.lower()
    return ("electric" not in low, "residential" not in low and "service" not in low, len(path))


def _path_words(path: str) -> str:
    return re.sub(r"[-_/]+", " ", path)


def _internal_path(href: str, host: str) -> str | None:
    """A link's path on this site, or None when it leaves the site."""
    try:
        target = urlparse(href.split("#")[0].split("?")[0])
    except ValueError:
        return None
    if target.netloc and target.netloc.removeprefix("www.") != host:
        return None
    return target.path.rstrip("/") if target.path.startswith("/") else None


def _job_paths(pattern: re.Pattern, soup: BeautifulSoup, site_paths: list[str],
               host: str) -> tuple[list[str], dict[str, str]]:
    """Paths that match one job's wording, and the menu wording for any we saw."""
    titles: dict[str, str] = {}
    paths = {p.rstrip("/") for p in site_paths if p and pattern.search(_path_words(p))}
    for link in soup.find_all("a", href=True):
        path = _internal_path(link["href"], host)
        anchor = link.get_text(" ", strip=True)
        if not path or not (pattern.search(anchor) or pattern.search(_path_words(path))):
            continue
        paths.add(path)
        if anchor and len(anchor) <= 60:
            titles.setdefault(path, anchor)
    return sorted(paths, key=lambda p: (bool(_EDITORIAL_PATH.search(p)), len(p))), titles


def _ev_paths(soup: BeautifulSoup, site_paths: list[str], host: str) -> tuple[list[str], dict[str, str]]:
    """Paths that are about EV work, and the menu wording for any we saw."""
    return _job_paths(EV_SERVICE, soup, site_paths, host)


def ev_profile(
    soup: BeautifulSoup,
    text: str,
    site_paths: list[str],
    host: str,
    fetch_page: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """How strongly a site sells EV work, and the specifics an email can name.

    The homepage is only the start: the sitemap catches pages the menu doesn't
    link, and a service hub catches shops that list EV work one click in.
    """
    paths, titles = _ev_paths(soup, site_paths, host)
    service_pages = [p for p in paths if not _EDITORIAL_PATH.search(p)]
    pages_read: list[str] = []
    if fetch_page is not None:
        wanted = service_pages[:1]
        if not paths and not EV_SERVICE.search(text):
            links = {_internal_path(a["href"], host) for a in soup.find_all("a", href=True)}
            wanted = sorted({p for p in [*links, *site_paths]
                             if p and _SERVICE_HUB.search(p) and not _EDITORIAL_PATH.search(p)},
                            key=_hub_rank)
        for path in wanted[:MAX_EV_PAGE_FETCHES]:
            page = fetch_page(path)
            if page:
                pages_read.append(_visible_text(BeautifulSoup(page, "html.parser")))
    combined = " ".join([text, *pages_read])
    shown = bool(paths or EV_SERVICE.search(combined))
    return {
        "ev_service": shown,
        "ev_strength": "page" if service_pages else "mention" if shown else None,
        "ev_page_path": service_pages[0] if service_pages else None,
        "ev_page_title": titles.get(service_pages[0]) if service_pages else None,
        "ev_brands": [name for name, pattern in EV_BRANDS.items()
                      if shown and re.search(pattern, combined, re.I)],
        "ev_commercial": bool(shown and _EV_COMMERCIAL.search(combined)),
    }


def permit_profile(
    soup: BeautifulSoup,
    text: str,
    site_paths: list[str],
    host: str,
    fetch_page: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Which of the four Permit Packets job types a site shows, and where.

    Reads pages the way ev_profile does and stays inside the same fetch limit:
    one service page per job type shown, or the service hubs when the homepage
    shows none. permit_job_pages only holds service pages, never /blog posts, and a job
    found only on an editorial path is not recorded.
    """
    found = {slug: _job_paths(rx, soup, site_paths, host)[0] for slug, rx in PERMIT_JOB_REGEX.items()}
    pages = {slug: [p for p in paths if not _EDITORIAL_PATH.search(p)] for slug, paths in found.items()}
    pages_read: list[str] = []
    if fetch_page is not None:
        wanted = [p[0] for p in pages.values() if p]
        if not any(pages.values()) and not any(rx.search(text) for rx in PERMIT_JOB_REGEX.values()):
            links = {_internal_path(a["href"], host) for a in soup.find_all("a", href=True)}
            wanted = sorted({p for p in [*links, *site_paths]
                             if p and _SERVICE_HUB.search(p) and not _EDITORIAL_PATH.search(p)},
                            key=_hub_rank)
        for path in list(dict.fromkeys(wanted))[:MAX_EV_PAGE_FETCHES]:
            page = fetch_page(path)
            if page:
                pages_read.append(_visible_text(BeautifulSoup(page, "html.parser")))
    combined = " ".join([text, *pages_read])
    # A job seen only on an editorial path (/blog, /expert-tips, /guides...) is not
    # recorded: it needs a service page or the text rule on the homepage or a read
    # service page.
    shown = [slug for slug, rx in PERMIT_JOB_REGEX.items() if pages[slug] or rx.search(combined)]
    return {
        "permit_jobs": shown,
        "permit_job_pages": {slug: pages[slug][0] for slug in shown if pages[slug]},
    }


_NAME = r"([A-Z][a-z]{2,14}(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z'’\-]{2,20})?)"
_OWNER_PATTERNS = (
    re.compile(rf"(?i:owned and operated by|owned by|founded by|started by|run by)\s+(?:(?i:master electrician)\s+)?{_NAME}"),
    re.compile(rf"{_NAME},?\s+(?:(?i:is)\s+)?(?:(?i:the|our)\s+)?(?i:owner|founder|co-founder|president|ceo)\b"),
    re.compile(rf"(?<!business )(?<!home )(?<!property )(?<!pool )\b(?i:owner|founder|president)[,:\s–—-]+{_NAME}"),
)


_NOT_A_NAME = {"our", "the", "your", "meet", "and", "with", "from", "company", "business", "family"}


def owner_name(texts: list[str], nodes: list[dict]) -> str | None:
    """The owner's name as a site states it. Callers still check it's a real first name."""
    for node in nodes:
        founder = node.get("founder")
        founder = founder[0] if isinstance(founder, list) and founder else founder
        name = founder.get("name") if isinstance(founder, dict) else founder
        if isinstance(name, str) and name.strip():
            return name.strip()
    found = [m.group(1) for text in texts for pattern in _OWNER_PATTERNS for m in pattern.finditer(text)
             if m.group(1).split()[0].lower() not in _NOT_A_NAME]
    return Counter(found).most_common(1)[0][0] if found else None


def schema_nodes(soup: BeautifulSoup) -> list[dict]:
    """Every JSON-LD node on the page, with @graph containers flattened."""
    out: list[dict] = []

    def walk(data: Any) -> None:
        if isinstance(data, list):
            for item in data:
                walk(item)
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                walk(graph)
            if data.get("@type"):
                out.append(data)

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or "{}"))
        except (ValueError, TypeError):
            continue
    return out


def _types(nodes: list[dict]) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        t = node.get("@type")
        for item in t if isinstance(t, list) else [t]:
            found.add(str(item).rsplit("/", 1)[-1].lower())
    return found


def _bot_access(robots: Any, url: str) -> dict[str, bool | None]:
    """{bot: allowed?}; None when there's no robots.txt to read."""
    if robots is None:
        return {bot: None for bot in AI_SEARCH_BOTS}
    out: dict[str, bool | None] = {}
    for bot in AI_SEARCH_BOTS:
        try:
            out[bot] = bool(robots.can_fetch(bot, url))
        except Exception:
            out[bot] = None
    return out


def _is_noindexed(soup: BeautifulSoup, headers: dict[str, str]) -> bool:
    tags = soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)})
    meta = " ".join((t.get("content") or "") for t in tags).lower()
    lowered = {k.lower(): v for k, v in headers.items()}
    return "noindex" in meta or "noindex" in (lowered.get("x-robots-tag") or "").lower()


def _visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return clone.get_text(" ", strip=True)


def _is_js_shell(soup: BeautifulSoup, visible_words: int) -> bool:
    """Almost no text in the HTML, and an empty app root waiting for JavaScript."""
    if visible_words >= 80:
        return False
    for key in _JS_APP_ROOTS:
        root = soup.find(id=key)
        if root is not None and len(root.get_text(" ", strip=True).split()) < 40:
            return True
    return False


def _place_terms(business: dict) -> list[str]:
    terms = [business.get("city"), (business.get("market") or "").split(",")[0]]
    return [t.strip().lower() for t in dict.fromkeys(t for t in terms if t and t.strip())]


def _towns(location_paths: list[str], business: dict) -> set[str]:
    towns = {_slug(t) for t in _place_terms(business)}
    for path in location_paths:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[-2] in _AREA_PARENTS:
            towns.add(parts[-1])
    return {t for t in towns if len(t) >= 3}


def service_city_paths(offering_paths: list[str], location_paths: list[str], business: dict,
                       offering_words: list[str]) -> list[str]:
    """Pages aimed at one service in one place: /drain-cleaning-vista, /vista/roof-repair."""
    towns = _towns(location_paths, business)
    words = [w.strip("-") for w in offering_words if len(w.strip("-")) >= 4]
    hits = []
    for path in sorted(set(offering_paths) | set(location_paths)):
        if any(town in path for town in towns) and any(word in path for word in words):
            hits.append(path)
    return hits


def _sample_page(html: str, path: str, business: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    text = _visible_text(soup)
    places = _place_terms(business)
    head = f"{title} {h1_text}".lower()
    return {
        "path": path,
        "title": title[:120],
        "h1": h1_text[:120],
        "words": len(text.split()),
        "names_location": any(p in head for p in places),
        "has_schema": bool(schema_nodes(soup)),
    }


def collect(
    *,
    business: dict,
    soup: BeautifulSoup,
    html: str,
    final_url: str,
    headers: dict[str, str],
    word_count: int,
    robots: Any,
    has_sitemap: bool,
    offering_paths: list[str],
    location_paths: list[str],
    offering_words: list[str],
    sample_page: Callable[[str], str | None] | None = None,
    site_paths: list[str] | None = None,
    fetch_page: Callable[[str], str | None] | None = None,
    other_page_texts: list[str] | None = None,
) -> dict[str, Any]:
    if fetch_page is not None:
        # ev_profile and permit_profile read the same pages. Fetch each once.
        fetch_page = functools.lru_cache(maxsize=None)(fetch_page)
    nodes = schema_nodes(soup)
    types = _types(nodes)
    text = _visible_text(soup)
    words = text.split()
    low_html = html.lower()
    places = _place_terms(business)
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    opening = " ".join(words[:150]).lower()
    trade_words = [w.strip("-").replace("-", " ") for w in offering_words]
    niche = str(business.get("vertical") or "").replace("_", " ")
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h2", "h3", "h4", "summary"])]
    images = soup.find_all("img")
    pairs = service_city_paths(offering_paths, location_paths, business, offering_words)
    same_as = [n.get("sameAs") for n in nodes if n.get("sameAs")]
    has_tel = any(a["href"].lower().startswith("tel:") for a in soup.find_all("a", href=True))
    # A menu can be images or icons, but its links still spell out the page.
    link_words = " ".join(re.sub(r"[-_/]+", " ", a["href"]) for a in soup.find_all("a", href=True))

    signals: dict[str, Any] = {
        "version": SIGNALS_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "indexable": not _is_noindexed(soup, headers),
        "js_only": _is_js_shell(soup, len(words)),
        "has_viewport": soup.find("meta", attrs={"name": "viewport"}) is not None,
        "has_canonical": soup.find("link", rel="canonical") is not None,
        "has_sitemap": has_sitemap,
        # None when no number is shown at all: there's nothing to make tappable.
        "has_click_to_call": (
            True if has_tel else False if _PHONE_TEXT.search(text) else None),
        "title_names_location": any(p in title.lower() for p in places) if title and places else None,
        "h1_names_location": any(p in h1_text.lower() for p in places) if h1_text and places else None,
        "clear_identity": (
            any(p in opening for p in places)
            and ((niche and niche in opening) or any(w in opening for w in trade_words))
        ) if places and words else None,
        "faq_content": (
            any(_FAQ_HEADING.search(h) for h in headings)
            or sum(1 for h in headings if h.endswith("?")) >= 2
        ),
        "faq_schema": "faqpage" in types,
        "service_schema": bool(types & {"service", "offercatalog"})
        or any(n.get("hasOfferCatalog") or n.get("makesOffer") for n in nodes),
        "profile_links_in_schema": bool(same_as),
        "analytics": [name for name, marks in ANALYTICS_MARKERS.items()
                      if any(m in low_html for m in marks)],
        "images": len(images),
        "images_missing_alt": sum(1 for i in images if not (i.get("alt") or "").strip()),
        "ai_bots": _bot_access(robots, final_url),
        **ev_profile(soup, f"{title} {text} {link_words}", site_paths or [],
                     urlparse(final_url).netloc.removeprefix("www."), fetch_page),
        **permit_profile(soup, f"{title} {text} {link_words}", site_paths or [],
                         urlparse(final_url).netloc.removeprefix("www."), fetch_page),
        "owner_name": owner_name([text, *(other_page_texts or [])], nodes),
        "offering_paths": len(offering_paths),
        "location_paths": len(location_paths),
        "service_city_paths": len(pairs),
        "service_city_examples": pairs[:4],
        "page_samples": None,
    }

    if sample_page is not None:
        wanted = (offering_paths[:4] + [p for p in location_paths if p not in offering_paths][:2])
        samples = []
        for path in wanted[:MAX_SAMPLED_PAGES]:
            page = sample_page(path)
            if page:
                samples.append(_sample_page(page, path, business))
        signals["page_samples"] = samples
    return signals


def _sampled(signals: dict) -> list[dict]:
    """Offering pages from the deep sample (location pages say their town anyway)."""
    return [s for s in (signals.get("page_samples") or [])
            if not any(part in _AREA_PARENTS for part in s["path"].split("/"))]


def blocked_ai_bots(signals: dict) -> list[str]:
    bots = signals.get("ai_bots") or {}
    return [AI_SEARCH_BOTS[b] for b in AI_SEARCH_BOTS if bots.get(b) is False]


def findings(signals: dict | None, profile: str) -> list[dict[str, Any]]:
    """Gaps as (signal, severity, points, finding, observed). Empty when unchecked."""
    if not signals:
        return []
    out: list[dict[str, Any]] = []

    def add(signal: str, severity: str, points: int, finding: str, **observed: Any) -> None:
        out.append({"signal": signal, "severity": severity, "points": points,
                    "finding": finding, "observed": observed})

    if signals.get("indexable") is False:
        add("noindex_homepage", "critical", 12,
            "The homepage tells search engines not to index it, so it can't appear in "
            "Google or in AI answers.")
    blocked = blocked_ai_bots(signals)
    if blocked:
        add("ai_crawlers_blocked", "high", 6,
            f"The site's robots.txt blocks {', '.join(blocked)}, so those tools can't read it.",
            blocked=blocked)
    if signals.get("js_only"):
        add("js_only_content", "high", 6,
            "The page text only appears after JavaScript runs. Many AI crawlers don't run "
            "JavaScript, so they see an almost empty page.")
    if signals.get("title_names_location") is False and signals.get("h1_names_location") is not True:
        add("title_missing_location", "medium", 4,
            "Neither the homepage title nor its main heading names the town it serves.")
    offering = int(signals.get("offering_paths") or 0)
    if (profile in SERVICE_CITY_PROFILES and offering >= 2
            and signals.get("has_sitemap") and not signals.get("service_city_paths")):
        add("no_service_city_pages", "medium", 5,
            f"The site has {offering} service pages but none aimed at a service in a "
            "specific town.", offering_pages=offering)
    if signals.get("clear_identity") is False:
        add("homepage_unclear", "medium", 3,
            "The opening of the homepage doesn't say plainly what the business does and where.")
    if signals.get("has_click_to_call") is False:
        add("no_click_to_call", "medium", 3,
            "The phone number isn't a tap-to-call link on the homepage.")
    if signals.get("faq_content") is False:
        add("no_faq_content", "low", 2, "The homepage doesn't answer common customer questions.")
    if signals.get("service_schema") is False:
        add("no_service_schema", "low", 2,
            "The site's structured data doesn't list the services it offers.")
    if signals.get("profile_links_in_schema") is False:
        add("no_schema_profile_links", "low", 1,
            "The structured data doesn't link to the business's other profiles.")
    if not signals.get("analytics"):
        add("no_analytics", "low", 2, "We didn't find analytics on the homepage.")
    total, missing = int(signals.get("images") or 0), int(signals.get("images_missing_alt") or 0)
    if total >= 4 and missing / total >= 0.5:
        add("images_missing_alt", "low", 1,
            f"{missing} of {total} homepage images have no text description.",
            images=total, missing=missing)
    pages = _sampled(signals)
    if pages:
        thin = [p for p in pages if p["words"] < THIN_PAGE_WORDS]
        if len(thin) * 2 >= len(pages):
            add("thin_service_pages", "medium", 0,
                f"{len(thin)} of the {len(pages)} service pages we read have under "
                f"{THIN_PAGE_WORDS} words.", sampled=len(pages), thin=len(thin))
        unlocated = [p for p in pages if not p["names_location"]]
        if len(unlocated) * 2 >= len(pages):
            add("service_pages_missing_location", "medium", 0,
                f"{len(unlocated)} of the {len(pages)} service pages we read don't name the "
                "town in their title or main heading.",
                sampled=len(pages), unlocated=len(unlocated))
    return out


def ai_readiness(signals: dict | None, audit: dict, business: dict) -> dict[str, Any] | None:
    """The report's AI search checklist. Unknown checks are shown, never failed."""
    if not signals:
        return None
    blocked = blocked_ai_bots(signals)
    bots = signals.get("ai_bots") or {}
    no_robots = all(v is None for v in bots.values())
    nap = audit.get("nap_matches_gbp")
    checks = [
        ("Search and AI crawlers can read the site",
         "not_checked" if no_robots and signals.get("indexable") else
         "fail" if blocked or signals.get("indexable") is False else "pass",
         f"Blocked: {', '.join(blocked)}" if blocked else
         "The homepage is set to noindex" if signals.get("indexable") is False else
         "No restrictions found"),
        ("Page text is in the HTML", "fail" if signals.get("js_only") else "pass",
         "Text only appears after JavaScript runs" if signals.get("js_only")
         else "Readable without running JavaScript"),
        ("Says what you do and where, right away",
         {True: "pass", False: "fail", None: "not_checked"}[signals.get("clear_identity")],
         "Named in the opening of the homepage" if signals.get("clear_identity")
         else "Not stated plainly in the opening text"),
        ("A page for each service", *_service_page_check(audit)),
        ("Answers common customer questions", "pass" if signals.get("faq_content") else "fail",
         "Question-and-answer content found" if signals.get("faq_content") else "None found on the homepage"),
        ("Business details in structured data",
         "pass" if audit.get("has_localbusiness_schema") else "fail",
         "Found" if audit.get("has_localbusiness_schema") else "Not found"),
        ("Linked to your other profiles", "pass" if signals.get("profile_links_in_schema") else "fail",
         "Listed in structured data" if signals.get("profile_links_in_schema") else "Not listed in structured data"),
        ("Phone number matches Google",
         {True: "pass", False: "review", None: "not_checked"}[nap],
         {True: "Matches", False: "Different number found, may be call tracking",
          None: "Couldn't confirm"}[nap]),
    ]
    rows = [{"label": label, "status": status, "detail": detail} for label, status, detail in checks]
    return {
        "checks": rows,
        "passed": sum(1 for r in rows if r["status"] == "pass"),
        "total": sum(1 for r in rows if r["status"] in {"pass", "fail"}),
    }


def _service_page_check(audit: dict) -> tuple[str, str]:
    if not audit.get("has_service_pages"):
        return "fail", "None found"
    count = int(audit.get("offering_page_count") or 0)
    return ("review", "Only 1 found") if count == 1 else ("pass", f"{count} found")


def site_structure(signals: dict | None, audit: dict) -> dict[str, Any] | None:
    if not signals:
        return None
    return {
        "offering_pages": int(audit.get("offering_page_count") or signals.get("offering_paths") or 0),
        "location_pages": int(audit.get("location_page_count") or signals.get("location_paths") or 0),
        "service_city_pages": int(signals.get("service_city_paths") or 0),
        "examples": signals.get("service_city_examples") or [],
        "total_pages": audit.get("sitemap_url_count"),
        "samples": signals.get("page_samples") or [],
    }

