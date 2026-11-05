"""A broken link on a site costs that link, never the crawl."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import enrich as E  # noqa: E402
import rescore  # noqa: E402

PLACEHOLDER = "https://[request-service-menu-url]/book"


def test_a_malformed_link_is_skipped():
    assert E._resolve_link("https://sparks.example.com", PLACEHOLDER) is None


def test_a_normal_link_still_resolves():
    full, parts = E._resolve_link("https://sparks.example.com", "/ev-chargers")
    assert full == "https://sparks.example.com/ev-chargers"
    assert parts.path == "/ev-chargers"


def test_crawl_survives_a_malformed_link(monkeypatch):
    html = f"""<html><title>Sparks</title><body>
        <a href="{PLACEHOLDER}">Book</a>
        <a href="/ev-chargers">EV Chargers</a>
        <p>We install EV chargers.</p></body></html>"""

    def fetch(session, url, **kwargs):
        if url.rstrip("/") != "https://sparks.example.com":
            return None
        return SimpleNamespace(url=url, text=html, content=html.encode(), status_code=200,
                               headers={"content-type": "text/html"}, elapsed=None, history=[])

    monkeypatch.setattr(E, "_fetch", fetch)
    found = E.crawl_site({"place_id": "p", "name": "Sparks", "vertical": "electrician",
                          "website_url": "https://sparks.example.com"})
    assert found.is_reachable
    assert found.site_signals["ev_service"] is True


def test_sitemap_with_a_malformed_url_keeps_the_good_ones(monkeypatch):
    xml = f"<urlset><url><loc>{PLACEHOLDER}</loc></url>" \
          "<url><loc>https://sparks.example.com/ev-chargers</loc></url></urlset>"
    monkeypatch.setattr(E, "_fetch", lambda *a, **k: SimpleNamespace(status_code=200, text=xml))
    monkeypatch.setattr(E, "_robots_ok", lambda *a: True)
    assert E._sitemap_paths(None, "https://sparks.example.com", {}) == ["/ev-chargers"]


def test_one_failed_site_does_not_stop_the_batch(monkeypatch):
    def crash(business):
        raise ValueError("broken site")

    monkeypatch.setattr(rescore.E, "crawl_business", crash)
    assert rescore.read_site({"name": "Sparks"}) is None


def test_a_mistyped_mailto_address_is_dropped():
    found = E._clean_emails({"info@southwest", "info@southwestelectric.com"},
                            "southwestelectric.com", "Southwest Electric")
    assert found == ["info@southwestelectric.com"]
