"""
Crawler regressions for open niches, against a local test site (no internet).

Each check is a false claim the old crawler would have made to a business:
  * a dentist marked up as "Dentist" told it has no business markup,
  * offering pages that only appear in the sitemap reported as missing,
  * a site with online booking told it has no way to be contacted,
  * location pages missed because they weren't San Diego city names.
"""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import config as C  # noqa: E402
import enrich as E  # noqa: E402

C.CRAWL_DELAY_S = 0  # local server, no politeness delay needed

HOME = """<!doctype html><html><head><title>Lakeline Family Dentistry | Austin TX</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Dentist","name":"Lakeline"}</script>
</head><body><h1>Family dentist in Austin</h1>
<a href="/about">About</a> <a href="/contact">Contact</a>
<a href="https://www.vagaro.com/lakeline/book">Book online</a>
<p>(512) 555-0100</p></body></html>"""

SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>http://{host}/</loc></url>
<url><loc>http://{host}/dental-implants/</loc></url>
<url><loc>http://{host}/invisalign/</loc></url>
<url><loc>http://{host}/round-rock-dentist/</loc></url>
</urlset>"""

PAGES = {
    "/": HOME,
    "/robots.txt": "User-agent: *\nAllow: /\n",
    "/about": "<html><body>About us</body></html>",
    "/contact": "<html><body>Call us</body></html>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        host = self.headers.get("Host")
        if self.path == "/sitemap.xml":
            body, ctype = SITEMAP.format(host=host), "application/xml"
        elif self.path in PAGES:
            body, ctype = PAGES[self.path], "text/html"
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"

broken = E.crawl_site({
    "place_id": "broken-link", "website_url": base + "/old-location-page/?utm_source=google",
    "vertical": "med_spa", "city": "Scottsdale", "phone": "(480) 555-0100",
})

# No website on the Google profile, but the business has one: find it by name.
E.candidate_domains = lambda b, limit=8: ["no-such-host.invalid", f"127.0.0.1:{server.server_port}"]
unlisted = E.crawl_unlisted({
    "place_id": "unlisted", "name": "Lakeline Family Dentistry", "vertical": "dentist",
    "city": "Austin", "phone": "(512) 555-0100",
})
stranger = E.crawl_unlisted({
    "place_id": "stranger", "name": "Other Dental Co", "vertical": "dentist",
    "city": "Denver", "phone": "(303) 555-0199",
})

business = {
    "place_id": "crawl-test",
    "website_url": base + "/",
    "vertical": "dentist",
    "city": "Round Rock",
    "market": "Austin, TX, USA",
    "phone": "(512) 555-0100",
}
f = E.crawl_site(business)
server.shutdown()

checks = [
    ("site was reachable", f.is_reachable),
    ("'Dentist' schema counts as business markup", f.has_localbusiness_schema),
    ("offering pages found via the sitemap", f.has_service_pages and f.offering_page_count >= 2),
    ("location page found from the business's own city", f.has_city_pages),
    ("online booking detected", f.has_online_booking and f.booking_provider == "Vagaro"),
    ("phone on site matches the profile", f.nap_matches_gbp is True),
    ("site missing from Google but found by name is crawled, not 'no website'",
     unlisted.site_source == "found" and unlisted.is_reachable and unlisted.has_localbusiness_schema),
    ("a site that doesn't match the business is never claimed as theirs",
     stranger.site_source == "gbp" and stranger.crawl_error == "no_website"),
    ("dead profile link with a working homepage is NOT 'site down'",
     (broken.crawl_error or "").startswith("profile_link_404")),
]

import scoring as S  # noqa: E402
base_line = S.Baseline("med_spa", "Scottsdale, AZ", 10, 50, 20, 80, 4.8, 90)
_, ev = S.score_website({"name": "Glow", "website_url": base + "/old/"}, broken, base_line)
_, ev2 = S.score_website({"name": "Lakeline"}, unlisted, base_line)
checks.append(("unlisted site scores as 'website not on Google', never 'no website'",
               "website_not_on_gbp" in [e.signal for e in ev2]
               and "no_website" not in [e.signal for e in ev2]))
checks.append(("broken profile link scores as its own finding",
               [e.signal for e in ev] == ["broken_profile_link"]))

ok = True
for label, passed in checks:
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    ok = ok and bool(passed)
print("\n" + ("ALL CHECKS PASSED" if ok else "*** SOME CHECKS FAILED ***"))
raise SystemExit(0 if ok else 1)
