"""What the crawl learns for outreach: EV proof, who to email and their name."""
from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import enrich as E  # noqa: E402
import site_signals as SS  # noqa: E402

from app.services.outreach_audit_copy import contact_first_name  # noqa: E402

HOST = "sparks.com"


def _profile(html: str, site_paths=(), pages=None):
    soup = BeautifulSoup(html, "html.parser")
    fetch = (lambda path: (pages or {}).get(path))
    return SS.ev_profile(soup, soup.get_text(" ", strip=True), list(site_paths), HOST, fetch)


def test_a_menu_link_counts_as_an_ev_page_and_keeps_its_wording():
    found = _profile('<a href="/ev-charger-installation">EV Charger Installation</a>')
    assert found["ev_strength"] == "page"
    assert found["ev_page_path"] == "/ev-charger-installation"
    assert found["ev_page_title"] == "EV Charger Installation"


def test_the_sitemap_finds_an_ev_page_the_homepage_never_links():
    found = _profile("<p>Licensed electricians.</p>", ["/about", "/services/ev-charger-installation"])
    assert found["ev_service"] is True
    assert found["ev_strength"] == "page"


def test_a_blog_post_is_a_mention_not_a_service_page():
    found = _profile("<p>Licensed electricians.</p>", ["/blog/how-ev-charging-works"])
    assert found["ev_service"] is True
    assert found["ev_strength"] == "mention"


def test_a_link_to_a_charger_brand_is_not_their_own_page():
    found = _profile('<a href="https://www.chargepoint.com/ev-charging">Partner</a>')
    assert found["ev_page_path"] is None
    assert found["ev_strength"] != "page"


def test_a_service_hub_is_read_when_the_homepage_shows_nothing():
    found = _profile('<a href="/services">Services</a><p>Licensed electricians.</p>',
                     pages={"/services": "<li>Panel upgrades</li><li>EV charger installs</li>"})
    assert found["ev_service"] is True


def test_the_ev_page_supplies_brands_and_commercial_work():
    page = "<h1>EV chargers</h1><p>We install Tesla Wall Connector and ChargePoint units, " \
           "plus commercial EV charging for workplaces.</p>"
    found = _profile('<a href="/ev-chargers">EV Chargers</a>', pages={"/ev-chargers": page})
    assert found["ev_brands"] == ["Tesla", "ChargePoint"]
    assert found["ev_commercial"] is True


def test_no_ev_work_means_no_brands():
    found = _profile("<p>We fix Tesla coils and panels.</p>")
    assert found["ev_service"] is False
    assert found["ev_brands"] == []


def test_owner_name_from_page_text_and_schema():
    assert SS.owner_name(["Owned and operated by Aaron Smith since 2009."], []) == "Aaron Smith"
    assert SS.owner_name(["Meet the team. Dave Ruiz, Owner"], []) == "Dave Ruiz"
    assert SS.owner_name(["Our founder, Maria Lopez, started the shop."], []) == "Maria Lopez"
    assert SS.owner_name([], [{"founder": {"name": "Tom Reed"}}]) == "Tom Reed"


def test_a_customer_testimonial_is_not_the_owner():
    assert SS.owner_name(["Great work. Jane Doe, business owner"], []) is None
    assert SS.owner_name(["Great work. Jane Doe, Homeowner"], []) is None


def test_only_a_real_first_name_reaches_the_greeting():
    assert contact_first_name("info@five.com", "Five Point Electric", "Aaron Smith") == "Aaron"
    assert contact_first_name("info@five.com", "Five Point Electric", "Operated Business") is None
    assert contact_first_name("sarah@five.com", "Five Point Electric", "Aaron Smith") == "Sarah"


def test_a_persons_address_beats_a_shared_inbox_and_the_wrong_desk():
    ranked = E.rank_emails(["careers@sparks.com", "info@sparks.com", "aaron@sparks.com",
                            "sparkselectric@gmail.com", "billing@sparks.com", "office@sparks.com"])
    assert ranked[:4] == ["aaron@sparks.com", "office@sparks.com", "info@sparks.com",
                          "sparkselectric@gmail.com"]
    assert set(ranked[4:]) == {"careers@sparks.com", "billing@sparks.com"}


def test_a_permit_inbox_counts_as_a_person():
    assert E.rank_emails(["info@sparks.com", "permits@sparks.com"])[0] == "permits@sparks.com"


def test_dead_mail_domains_are_dropped_and_lookup_failures_are_kept(monkeypatch):
    calls = []

    def takes_mail(domain):
        calls.append(domain)
        return domain != "dead.com"

    monkeypatch.setattr(E, "domain_takes_mail", takes_mail)
    kept = E.drop_undeliverable(["a@dead.com", "b@live.com", "c@gmail.com"])
    assert kept == ["b@live.com", "c@gmail.com"]
    assert "gmail.com" not in calls


def test_a_failed_dns_lookup_keeps_the_address(monkeypatch):
    def fail(*args, **kwargs):
        raise E.dns.exception.Timeout()

    E.domain_takes_mail.cache_clear()
    monkeypatch.setattr(E.dns.resolver, "resolve", fail)
    assert E.domain_takes_mail("slow-dns.com") is True
    E.domain_takes_mail.cache_clear()


def test_no_mail_server_drops_the_domain(monkeypatch):
    def none(*args, **kwargs):
        raise E.dns.resolver.NoAnswer()

    E.domain_takes_mail.cache_clear()
    monkeypatch.setattr(E.dns.resolver, "resolve", none)
    assert E.domain_takes_mail("no-mail.com") is False
    E.domain_takes_mail.cache_clear()
