"""Depth checks against fixture pages. Each check guards a claim made to a business."""
from __future__ import annotations

import os
import tempfile
import time
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

import enrich as E
import pipeline as P
import scoring as S
import site_signals as SS

BUSINESS = {"place_id": "p", "name": "Vista Drain Co", "city": "Vista",
            "market": "Vista, CA, USA", "vertical": "plumber", "phone": "(760) 555-0100"}
WORDS = ["drain-cleaning", "water-heater", "repipe", "service"]
checks: list[tuple[str, bool]] = []


def collect(html, *, robots=None, headers=None, offering=(), location=(), sitemap=True, sample=None):
    soup = BeautifulSoup(html, "html.parser")
    return SS.collect(
        business=BUSINESS, soup=soup, html=html, final_url="https://x.co/", headers=headers or {},
        word_count=len(soup.get_text().split()), robots=robots, has_sitemap=sitemap,
        offering_paths=list(offering), location_paths=list(location),
        offering_words=WORDS, sample_page=sample,
    )


def robots(text):
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser


def signals_of(found):
    return {f["signal"] for f in found}


GOOD = """<html><head><title>Vista Plumber | Vista Drain Co</title>
<meta name=viewport content=x>
<script type="application/ld+json">{"@graph":[{"@type":"Plumber","sameAs":["https://fb.com/x"],
"hasOfferCatalog":{"name":"s"}}]}</script><script>gtag('x')</script></head>
<body><h1>Vista plumbing service</h1><p>Vista Drain Co is a plumber serving Vista, CA.</p>
<a href="tel:7605550100">(760) 555-0100</a><h2>Frequently asked questions</h2>
<img src=a alt=b></body></html>"""
BARE = """<html><head><title>Welcome</title></head><body><h1>Home</h1>
<p>We care about quality and people. Call (760) 555-0100.</p></body></html>"""

good = collect(GOOD, robots=robots("User-agent: *\nAllow: /"),
               offering=["/drain-cleaning-vista", "/water-heater"], location=["/service-areas/vista"])
checks.append(("a healthy site produces no gaps", SS.findings(good, "home_service") == []))
checks.append(("service + town page is recognised", good["service_city_paths"] >= 1))

bare = collect(BARE, offering=["/drain-cleaning", "/water-heater"])
found = signals_of(SS.findings(bare, "home_service"))
checks.append(("town missing from title and heading is flagged", "title_missing_location" in found))
checks.append(("visible phone with no tel: link is flagged", "no_click_to_call" in found))
checks.append(("service pages with no town page is flagged", "no_service_city_pages" in found))
checks.append(("unclear homepage is flagged", "homepage_unclear" in found))
checks.append(("no robots.txt is NOT a block", "ai_crawlers_blocked" not in found))

no_map = collect(BARE, offering=["/a-service", "/b-service"], sitemap=False)
checks.append(("no sitemap means we stay quiet on town pages",
               "no_service_city_pages" not in signals_of(SS.findings(no_map, "home_service"))))
checks.append(("real estate isn't told to build service + town pages",
               "no_service_city_pages" not in signals_of(SS.findings(bare, "real_estate"))))
no_phone = collect("<html><body><p>Hello</p></body></html>")
checks.append(("no phone shown: says nothing about tap to call",
               "no_click_to_call" not in signals_of(SS.findings(no_phone, "home_service"))))

blocked = collect(GOOD, robots=robots("User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /"))
checks.append(("blocking a search crawler is flagged by name",
               SS.blocked_ai_bots(blocked) == ["ChatGPT search"]))
training = collect(GOOD, robots=robots("User-agent: GPTBot\nDisallow: /"))
checks.append(("blocking a training crawler alone is NOT flagged",
               SS.blocked_ai_bots(training) == []))

noindex = collect('<html><head><meta name="robots" content="noindex"></head><body>x</body></html>')
checks.append(("noindex meta tag is caught", noindex["indexable"] is False))
checks.append(("noindex header is caught",
               collect(GOOD, headers={"X-Robots-Tag": "noindex"})["indexable"] is False))
checks.append(("empty JS app shell is caught",
               collect('<html><body><div id="root"></div><script src=a></script></body></html>')["js_only"]))
checks.append(("a real page isn't called a JS shell", good["js_only"] is False))

pages = {"/drain-cleaning": "<title>Drains</title><h1>Drains</h1><p>short</p>",
         "/water-heater": "<title>Heaters in Vista</title><h1>Heaters</h1>" + "<p>word</p>" * 300}
deep = collect(BARE, offering=list(pages), sample=pages.get)
deep_found = signals_of(SS.findings(deep, "home_service"))
checks.append(("thin service pages are flagged from the sample", "thin_service_pages" in deep_found))
checks.append(("service pages without the town are flagged",
               "service_pages_missing_location" in deep_found))
checks.append(("a failed page fetch is skipped",
               len(collect(BARE, offering=["/gone"], sample=lambda p: None)["page_samples"]) == 0))

ready = SS.ai_readiness(bare, {"nap_matches_gbp": None}, BUSINESS)
checks.append(("unknown checks aren't counted against the site",
               ready["total"] < len(ready["checks"])))
checks.append(("readiness counts match its rows",
               ready["passed"] == sum(1 for c in ready["checks"] if c["status"] == "pass")))

# Emails hidden from scrapers but shown to visitors.
cf = "".join(f"{b:02x}" for b in [0x42] + [c ^ 0x42 for c in b"joe@vistadrain.com"])
html = f'<a href="/cdn-cgi/l/email-protection#{cf}">email</a><p>sales [at] vistadrain [dot] com</p>'
emails = E.extract_emails(html, BeautifulSoup(html, "html.parser"))
checks.append(("Cloudflare-protected email is decoded", "joe@vistadrain.com" in emails))
checks.append(("written-out email is read", "sales@vistadrain.com" in emails))
checks.append(("email on the business's other domain is kept",
               E._clean_emails({"joe@vistadrainco.com"}, "vistadrain-ca.com", "Vistadrain Co") != []))
checks.append(("an agency's email is still rejected",
               E._clean_emails({"mike@agency.com"}, "vistadrain.com", "Vista Drain Co") == []))
checks.append(("placeholder and no-reply addresses are rejected",
               E._clean_emails({"you@yourdomain.com", "noreply@vistadrain.com"}, "vistadrain.com") == []))

# One hung site costs one lead, and a batch limit never quarantines the unvisited.
E.C.SITE_CRAWL_CAP_S = 0.2
real_crawl = E.crawl_site
E.crawl_site = lambda b: time.sleep(5)
hung = E.crawl_business({"place_id": "h", "website_url": "https://x.co"})
E.crawl_site = real_crawl
checks.append(("a hung site is capped and quarantined on its own",
               hung.crawl_error == "blocked_crawl_hang"))

P.CACHE_FILE = os.path.join(tempfile.mkdtemp(), "cache.json")
fresh = E.SiteFindings(place_id="fresh", is_reachable=True, site_signals=good)
P.save_cache({
    "hang": E.SiteFindings(place_id="hang", crawl_error="blocked_crawl_hang"),
    "old": E.SiteFindings(place_id="old", is_reachable=True),
    "fresh": fresh,
    "gone": E.SiteFindings(place_id="gone", crawl_error="http_500"),
})
checks.append(("a new sweep forgets quarantined and outdated crawls", P.prune_cache() == 2))
checks.append(("a recent crawl is kept", set(P.load_cache()) == {"fresh", "gone"}))

# Evidence reaches scoring, and old crawls with no signals are unaffected.
base = S.Baseline("plumber", "Vista, CA, USA", 10, 20, 10, 40, 4.5, 90)
w = E.SiteFindings(place_id="p", is_reachable=True, has_ssl=True, title="t", title_length=30,
                   meta_description="m", h1_count=1, word_count=800, has_service_pages=True,
                   has_city_pages=True, has_localbusiness_schema=True, has_contact_form=True,
                   has_gbp_link=True, site_signals=bare)
checks.append(("depth findings count toward the website axis",
               S.score_website(BUSINESS, w, base)[0] > 0))

ok = True
for label, passed in checks:
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    ok = ok and passed
print("\n" + ("ALL CHECKS PASSED" if ok else "*** SOME CHECKS FAILED ***"))
raise SystemExit(0 if ok else 1)
