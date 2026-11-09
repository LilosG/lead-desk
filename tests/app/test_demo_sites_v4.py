import random
import re
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.services import demo_sites as demo_sites_module
from app.services.demo_brand import extract_brand
from app.services.demo_design import contrast, design_tokens, icon_name, palette_with_brand, style_for
from app.services.demo_site_renderer_v4 import hours_rows, hours_summary, render_demo_site_v4
from app.services.demo_sites import DemoSiteService

from tests.app.test_demo_sites_v3 import FakeDemoRepository

WEEK = [
    "Monday: 7:00 AM – 5:00 PM", "Tuesday: 7:00 AM – 5:00 PM",
    "Wednesday: 7:00 AM – 5:00 PM", "Thursday: 7:00 AM – 5:00 PM",
    "Friday: 7:00 AM – 5:00 PM", "Saturday: 8:00 AM – 12:00 PM", "Sunday: Closed",
]


# --- hours -------------------------------------------------------------------

def test_hours_group_consecutive_days():
    rows = hours_rows({"weekdayDescriptions": WEEK})
    assert rows == [("Mon–Fri", "7:00 AM – 5:00 PM"), ("Sat", "8:00 AM – 12:00 PM"), ("Sun", "Closed")]
    assert hours_summary(rows) == "Open Mon–Sat"


def test_hours_summaries():
    every_day = {"weekdayDescriptions": [f"{d}: Open 24 hours" for d in
                                         ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]}
    assert hours_summary(hours_rows(every_day)) == "Open 24/7"
    gaps = [WEEK[0], "Tuesday: Closed", *WEEK[2:6], "Sunday: Closed"]
    assert hours_summary(hours_rows({"weekdayDescriptions": gaps})) == "Open 5 days a week"
    assert hours_rows(None) == [] and hours_rows({"weekdayDescriptions": WEEK[:3]}) == []


# --- colour and icons --------------------------------------------------------

def test_tokens_keep_text_readable_for_any_palette():
    rng = random.Random(7)
    for _ in range(200):
        color = lambda: "#" + "".join(f"{rng.randrange(256):02x}" for _ in range(3))  # noqa: E731
        t = design_tokens({"ink": color(), "accent": color(), "surface": "#f5f5f5"})
        assert contrast(t["ink"], "#ffffff") >= 7
        assert contrast(t["accent_text"], "#ffffff") >= 4.5
        assert contrast(t["accent"], t["on_accent"]) >= 3


def test_brand_colour_becomes_ink_or_accent_and_greys_are_ignored():
    base = {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"}
    assert palette_with_brand(base, "#0b3d2e")["ink"] == "#0b3d2e"
    assert palette_with_brand(base, "#e63946")["accent"] == "#e63946"
    assert palette_with_brand(base, "#888888") == base
    assert palette_with_brand(base, "not a colour") == base


def test_styles_follow_the_niche_and_can_be_overridden():
    assert style_for("home_service") == "bold"
    assert style_for("medical_aesthetic") == "soft"
    assert style_for("dental") == "clean"
    assert style_for("unknown") == "clean"
    assert style_for("home_service", "soft") == "soft"


def test_icons_match_services():
    assert icon_name("EV Charger Installation") == "plug"
    assert icon_name("Car Accidents") == "scale"
    assert icon_name("Dental Implants") == "tooth"
    assert icon_name("Something Unusual") == "check"


# --- page --------------------------------------------------------------------

def _source(**overrides):
    source = {
        "name": "Volt <Electric>", "city": "Vista", "state": "CA", "phone": "(760) 229-3096",
        "primary_type_display": "Electrician", "niche_profile": "home_service",
        "rating": 4.8, "review_count": 126, "google_maps_uri": "https://maps.google.com/?cid=1",
        "reviews": [{"author": "Dana M.", "rating": 5, "text": "Great work, clear pricing and very tidy.", "date": "October 2026"}],
        "hours": {"weekdayDescriptions": WEEK}, "street": "2130 E Main St",
        "address": "2130 E Main St, Vista, CA 92084",
    }
    source.update(overrides)
    return source


def _content(**overrides):
    content = {"headline": "Vista's 4.8-star electrician", "subheadline": "Hello.",
               "services": ["Panel Upgrades", "EV Charger Installation", "Rewiring"],
               "service_areas": ["Vista", "Oceanside", "San Marcos"]}
    content.update(overrides)
    return content


def _render(source=None, content=None, **brand):
    return render_demo_site_v4(
        source=source or _source(), content=content or _content(),
        brand={"style": "bold", "palette": {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"}, **brand},
    )


def test_page_shows_real_listing_details_and_escapes_text():
    html = _render()
    assert "Volt &lt;Electric&gt;" in html and "Volt <Electric>" not in html
    assert "Mon–Fri" in html and "8:00 AM – 12:00 PM" in html
    assert "2130 E Main St, Vista, CA 92084" in html
    assert "maps.google.com/maps?q=" in html
    assert 'class="style-bold"' in html
    assert "Not affiliated with or endorsed by" in html
    assert "aggregateRating" not in html


def test_page_makes_no_unbacked_claims():
    lowered = re.sub(r"<[^>]+>", " ", _render()).lower()
    for claim in ("licensed", "insured", "guarantee", "years of experience", "free estimate", "24/7", "same-day"):
        assert claim not in lowered, claim


def test_hidden_address_means_no_map_and_no_street():
    html = _render(_source(street=None, address="Vista, CA, USA"))
    assert "maps.google.com/maps?q=" not in html
    assert "Serving Vista, CA" in html


def test_thin_listing_still_renders_a_complete_page():
    html = _render(_source(rating=None, review_count=None, reviews=[], hours=None, street=None, phone=None),
                   _content(service_areas=["Vista"]))
    assert 'id="reviews"' not in html
    assert "stats-spacer" in html
    assert 'href="#contact"' in html
    assert "</html>" in html


def test_logo_and_style_variants_render():
    html = _render(logo_url="https://demo.example/_media/k/logo.png", logo_on_dark=True, style="soft")
    assert 'class="logo-chip dark"' in html and 'class="style-soft"' in html
    assert "family=Fraunces" in html


# --- brand extraction --------------------------------------------------------

def _png(color=(200, 30, 40), size=(240, 80), transparent=False):
    image = Image.new("RGBA", size, (*color, 255))
    if transparent:
        image.putpixel((0, 0), (0, 0, 0, 0))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_extract_brand_saves_header_logo_and_colour(tmp_path: Path):
    page = b'''<html><head></head><body><header><a href="/"><img src="/img/site-logo.png" alt="Volt Electric"></a></header>
    <footer><img src="/img/bbb-logo.png" alt="BBB logo"></footer></body></html>'''
    files = {"https://volt.example/": page, "https://volt.example/img/site-logo.png": _png()}
    result = extract_brand("https://volt.example/", place_id="p1", business_name="Volt Electric",
                           root=tmp_path, base_url="https://demo.example", fetch=lambda url, limit: files.get(url))
    assert result["logo_url"].startswith("https://demo.example/_media/")
    assert result["color"] and result["color"].startswith("#")
    saved = list(tmp_path.glob("_media/*/logo-*.png"))
    assert len(saved) == 1


def test_extract_brand_ignores_badges_and_survives_failures(tmp_path: Path):
    page = b'<html><body><footer><img src="/bbb-logo.png" alt="BBB logo"></footer></body></html>'
    files = {"https://volt.example/": page, "https://volt.example/bbb-logo.png": _png()}
    result = extract_brand("https://volt.example/", place_id="p1", business_name="Volt Electric",
                           root=tmp_path, base_url="https://demo.example", fetch=lambda url, limit: files.get(url))
    assert result["logo_url"] is None

    def boom(url, limit):
        raise RuntimeError("network down")
    assert extract_brand("https://volt.example/", place_id="p1", root=tmp_path,
                         base_url="https://demo.example", fetch=boom)["logo_url"] is None


def test_theme_colour_is_used_when_present(tmp_path: Path):
    page = b'<html><head><meta name="theme-color" content="#1d6fb8"></head><body></body></html>'
    result = extract_brand("https://volt.example/", place_id="p1", root=tmp_path, base_url="https://demo.example",
                           fetch=lambda url, limit: page if url == "https://volt.example/" else None)
    assert result["color"] == "#1d6fb8"


# --- service -----------------------------------------------------------------

class V4Repo:
    def get_prospect(self, place_id):
        return {"place_id": place_id, "name": "Volt Electric", "vertical": "electrician", "primary_type": "electrician",
                "city": "Vista", "state": "CA", "phone": "(760) 229-3096", "website_url": "https://volt.example/",
                "rating": 4.8, "review_count": 126}

    def get_demo_details(self, place_id):
        return {"hours_json": {"weekdayDescriptions": WEEK}, "street": "2130 E Main St",
                "formatted_address": "2130 E Main St, Vista, CA 92084"}


def test_create_v4_demo_records_style_brand_and_details(monkeypatch, tmp_path):
    monkeypatch.setattr(demo_sites_module, "extract_brand", lambda *a, **k: {
        "color": "#e63946", "logo_url": "https://demo.example/_media/k/logo.png", "logo_on_dark": False,
        "source": "https://volt.example/"})
    demo = DemoSiteService(V4Repo(), FakeDemoRepository()).create_demo(
        "p1", template_key="premium-v4", services=[], service_areas=[], headline=None, subheadline=None,
        media_root=tmp_path, media_base_url="https://demo.example",
    )
    brand = demo["brand_snapshot"]
    assert brand["style"] == "bold" and brand["palette"]["accent"] == "#e63946"
    assert brand["logo_url"].endswith("logo.png")
    assert demo["source_snapshot"]["street"] == "2130 E Main St"
    assert "logo-chip" in demo["html_document"]


def test_create_v4_demo_without_branding_or_when_extraction_breaks(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("bad site")
    monkeypatch.setattr(demo_sites_module, "extract_brand", boom)
    service = DemoSiteService(V4Repo(), FakeDemoRepository())
    broken = service.create_demo("p1", template_key="premium-v4-soft", services=[], service_areas=[],
                                 headline=None, subheadline=None, media_root=tmp_path, media_base_url="https://d.example")
    assert broken["brand_snapshot"]["style"] == "soft" and broken["brand_snapshot"]["logo_url"] is None
    off = service.create_demo("p1", template_key="premium-v4", services=[], service_areas=[], headline=None,
                              subheadline=None, use_site_branding=False, media_root=tmp_path, media_base_url="https://d.example")
    assert off["brand_snapshot"]["palette"]["accent"] == "#f0b22c"


def test_v3_demos_are_unchanged_by_v4(tmp_path):
    demo = DemoSiteService(V4Repo(), FakeDemoRepository()).create_demo(
        "p1", template_key="trade-modern-v3", services=["Panel Upgrades"], service_areas=["Vista"],
        headline=None, subheadline=None, media_root=tmp_path, media_base_url="https://demo.example",
    )
    assert "style" not in demo["brand_snapshot"] and "hours" not in demo["source_snapshot"]
    assert "Concept website prepared by Lilos Growth" in demo["html_document"]


# --- polish: forms, areas, quotes, photo rules ------------------------------

def test_concept_lead_forms_never_send_anything():
    html = _render()
    assert 'id="hero-form"' in html and 'id="contact-form"' in html
    assert 'action="#"' in html and "e.preventDefault()" in html
    assert "nothing was sent" in html
    assert "<option>Panel Upgrades</option>" in html


def test_areas_section_has_a_card_per_town():
    html = _render(content=_content(service_areas=["Vista", "Oceanside", "San Marcos", "Carlsbad"]))
    assert html.count('class="area-card"') == 4
    assert "Electrician in Oceanside" in html
    assert "Serving Vista, Oceanside, San Marcos and nearby." in html
    single = _render(content=_content(service_areas=["Vista"]))
    assert 'class="area-card"' not in single and 'class="chips"' in single


def test_featured_quote_ends_at_a_sentence_when_it_can():
    from app.services.demo_site_renderer_v4 import _quote_excerpt
    text = ("They came out the same week and walked me through every option. " * 3) + "The rest is long " * 30
    quote = _quote_excerpt(text)
    assert 140 <= len(quote) <= 260 and quote.endswith(".")
    assert _quote_excerpt("Short and sweet.") == "Short and sweet."


def test_photo_prompts_ban_people_and_collages():
    from app.services.demo_media import DemoMediaService
    prompt = DemoMediaService._prompt({"primary_type": "electrician", "vertical": "electrician", "city": "Fresno"},
                                      role="work", direction=None)
    assert "Show no people" in prompt and "never a collage" in prompt
