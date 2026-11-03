from __future__ import annotations

import json
from datetime import date
from html import escape
from typing import Any

from app.services.demo_service_copy import describe_service


V3_TEMPLATE_OPTION = {
    "key": "trade-modern-v3",
    "name": "Local Business Homepage",
    "description": (
        "Full homepage with a hero, services, reputation, how it works, areas served, FAQ, "
        "a full footer and contact calls to action throughout. Wording adapts to the niche."
    ),
}


# Copy that changes with the kind of business, so a dental office isn't told
# about "homeowners" and "projects". Keyed by niche profile name.
NICHE_COPY: dict[str, dict[str, str]] = {
    "home_service": {"audience": "homeowners", "unit": "service", "engagement": "project",
                     "cta": "Request service", "start": "Choose the service you need",
                     "details": "Share the property location, scope, timing, and other details needed to confirm availability."},
    "medical_aesthetic": {"audience": "clients", "unit": "treatment", "engagement": "appointment",
                          "cta": "Book a consultation", "start": "Choose the treatment you're interested in",
                          "details": "Share your goals and timing so the team can recommend the right next step."},
    "dental": {"audience": "patients", "unit": "treatment", "engagement": "appointment",
               "cta": "Book an appointment", "start": "Choose the care you need",
               "details": "Share your needs, insurance questions and preferred times so the office can confirm availability."},
    "real_estate": {"audience": "buyers and sellers", "unit": "service", "engagement": "move",
                    "cta": "Schedule a call", "start": "Tell us whether you're buying or selling",
                    "details": "Share the neighborhoods, price range and timing you have in mind."},
    "legal": {"audience": "clients", "unit": "practice area", "engagement": "case",
              "cta": "Request a consultation", "start": "Choose the practice area that fits",
              "details": "Share the basics of your situation so the firm can confirm whether it can help."},
    "wellness_health": {"audience": "patients", "unit": "service", "engagement": "visit",
                        "cta": "Book a visit", "start": "Choose the care you need",
                        "details": "Share what's going on and your preferred times so the team can confirm availability."},
    "auto": {"audience": "drivers", "unit": "service", "engagement": "repair",
             "cta": "Schedule service", "start": "Choose the service your vehicle needs",
             "details": "Share the vehicle, the issue and your timing so the shop can confirm availability."},
    "generic_local_business": {"audience": "customers", "unit": "service", "engagement": "request",
                               "cta": "Get in touch", "start": "Choose what you need",
                               "details": "Share the details and timing so the business can confirm availability."},
}


def niche_copy(profile: str | None) -> dict[str, str]:
    return NICHE_COPY.get(profile or "", NICHE_COPY["generic_local_business"])


def star_string(rating: float | None) -> str:
    """Stars that match the real rating (rounded to the nearest whole star)."""
    if rating is None:
        return ""
    full = max(0, min(5, int(round(float(rating)))))
    return "★" * full + "☆" * (5 - full)


def _excerpt(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def _review_cards(reviews: list[dict[str, Any]]) -> list[str]:
    """Real reviews, each credited to its author and linked back to Google."""
    cards = []
    for review in reviews:
        author_raw = str(review.get("author") or "")
        if not author_raw:
            continue
        author = _safe(author_raw)
        rating = int(review.get("rating") or 5)
        photo = (
            f'<img src="{_safe(review["author_photo"])}" alt="" loading="lazy" referrerpolicy="no-referrer" />'
            if review.get("author_photo") else ""
        )
        name = (
            f'<a href="{_safe(review["author_url"])}" target="_blank" rel="noopener">{author}</a>'
            if review.get("author_url") else author
        )
        source = (
            f'<a href="{_safe(review["url"])}" target="_blank" rel="noopener">Posted on Google</a>'
            if review.get("url") else "Posted on Google"
        )
        date = f'{_safe(review["date"])} · ' if review.get("date") else ""
        cards.append(
            f'''<article class="review-card"><div class="review-stars" aria-label="{rating} out of 5">{star_string(rating)}</div>
            <p>{_safe(_excerpt(str(review.get("text") or "")))}</p>
            <footer><span class="review-avatar">{_safe(author_raw[:1].upper())}{photo}</span><span class="review-meta"><strong>{name}</strong><small>{date}{source}</small></span></footer></article>'''
        )
    return cards


def _safe(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _phone_href(phone: str | None) -> str:
    if not phone:
        return "#contact"
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return f"tel:{digits}" if digits else "#contact"


def _schema_json(source: dict[str, Any], services: list[str], service_areas: list[str]) -> str:
    schema: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": source.get("name"),
    }
    if source.get("phone"):
        schema["telephone"] = source["phone"]
    if source.get("city") or source.get("state"):
        schema["areaServed"] = [
            {"@type": "City", "name": area}
            for area in service_areas[:8]
        ] or [{"@type": "City", "name": source.get("city")}]
    if services:
        schema["knowsAbout"] = services[:6]
    # No aggregateRating: Google's guidelines don't allow a business to mark up
    # reviews collected on a third-party site (its Google reviews) as its own.
    return json.dumps(schema, separators=(",", ":")).replace("</", "<\\/")


def render_demo_site_v3(
    *,
    source: dict[str, Any],
    content: dict[str, Any],
    brand: dict[str, Any],
) -> str:
    business_name_raw = str(source.get("name") or "Local Service Company")
    business_name = _safe(business_name_raw)
    city_raw = str(source.get("city") or "your area")
    city = _safe(city_raw)
    state = _safe(source.get("state"))
    location = ", ".join(part for part in [city, state] if part)
    phone_raw = source.get("phone")
    phone = _safe(phone_raw)
    category_raw = str(source.get("primary_type_display") or "Local Business")
    copy = niche_copy(source.get("niche_profile"))
    unit = copy["unit"]
    engagement = copy["engagement"]
    stars = star_string(rating if (rating := source.get("rating")) is not None else None)
    category = _safe(category_raw)
    category_lower = _safe(category_raw.lower())
    rating = source.get("rating")
    review_count = source.get("review_count")
    services = [str(item).strip() for item in content.get("services", []) if str(item).strip()]
    service_areas = [str(item).strip() for item in content.get("service_areas", []) if str(item).strip()]
    if not services:
        services = [category_raw]
    if not service_areas:
        service_areas = [city_raw]

    headline = _safe(content.get("headline") or f"Local {category_raw.lower()} service for {city_raw}")
    subheadline = _safe(
        content.get("subheadline")
        or f"Explore {business_name_raw}'s services and get in touch directly for help in {city_raw} and nearby areas."
    )
    hero_image = _safe(content.get("hero_image_url"))
    work_image = _safe(content.get("work_image_url"))
    secondary_image = _safe(content.get("secondary_image_url"))
    palette = brand.get("palette") or {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"}
    call_href = _safe(_phone_href(phone_raw))
    call_label = f"Call {phone}" if phone else copy["cta"]

    reputation_text = ""
    if rating is not None and review_count is not None:
        reputation_text = f"{float(rating):.1f} Google rating · {int(review_count):,} reviews"
    elif review_count is not None:
        reputation_text = f"{int(review_count):,} Google reviews"

    hero_photo = (
        f'<img class="hero-photo" src="{hero_image}" alt="{business_name}, {category_lower}" loading="eager" />'
        if hero_image else ""
    )
    hero_class = "hero has-photo" if hero_image else "hero"

    proof_card = ""
    if reputation_text:
        proof_card = (
            f'<div class="proof-card"><div class="stars" aria-label="{_safe(rating)} out of 5">{stars}</div>'
            f'<strong>{_safe(reputation_text)}</strong><span>On Google</span></div>'
        )

    service_cards = "".join(
        f'''<article class="service-card">
          <div class="service-icon">{index:02d}</div>
          <h3>{_safe(service)}</h3>
          <p>{_safe(describe_service(service, index, unit))}</p>
          <a href="{call_href}">Ask about this {unit} <span>→</span></a>
        </article>'''
        for index, service in enumerate(services[:6], start=1)
    )

    area_chips = "".join(f"<li>{_safe(area)}</li>" for area in service_areas[:8])
    service_names = ", ".join(_safe(item) for item in services[:4])
    area_names = ", ".join(_safe(item) for item in service_areas[:5])

    media = ""
    if work_image:
        media = f'<img class="about-photo" src="{work_image}" alt="{business_name} at work" loading="lazy" />'
    elif secondary_image:
        media = f'<img class="about-photo" src="{secondary_image}" alt="{business_name} local service" loading="lazy" />'

    photo_band = ""
    if secondary_image and work_image:
        photo_band = f'''<section class="photo-band" aria-label="{business_name} service photography">
          <img src="{secondary_image}" alt="{business_name} local service" loading="lazy" />
        </section>'''

    rating_stat = (
        f'<strong>{float(rating):.1f}</strong><span>Google rating</span>'
        if rating is not None
        else f'<strong>{len(services[:6])}</strong><span>{_safe(unit.capitalize())}s offered</span>'
    )
    review_stat = (
        f'<strong>{int(review_count):,}</strong><span>Google reviews</span>'
        if review_count is not None
        else f'<strong>{len(service_areas[:8])}</strong><span>Areas served</span>'
    )

    maps_url = _safe(source.get("google_maps_uri"))
    reviews_link = (
        f'<p><a class="text-link" href="{maps_url}" target="_blank" rel="noopener">Read the reviews on Google →</a></p>'
        if maps_url else ""
    )
    reputation_section = ""
    review_cards = _review_cards(source.get("reviews") or [])
    if review_cards and rating is not None and review_count is not None:
        all_reviews = (
            f'<a class="text-link" href="{maps_url}" target="_blank" rel="noopener">Read all {int(review_count):,} on Google →</a>'
            if maps_url else ""
        )
        reputation_section = f'''<section class="reputation" id="reviews">
          <div class="wrap">
            <div class="reviews-head">
              <div>
                <div class="section-kicker">Google reviews</div>
                <h2>What {copy["audience"]} say about {business_name}.</h2>
              </div>
              <div class="reviews-summary"><strong>{float(rating):.1f}</strong><div><div class="stars" aria-label="{float(rating):.1f} out of 5">{stars}</div><span>{int(review_count):,} Google reviews</span></div></div>
            </div>
            <div class="review-grid" style="--cols:{len(review_cards)}">{"".join(review_cards)}</div>
            <p class="reviews-more">{all_reviews}</p>
          </div>
        </section>'''
    elif rating is not None and review_count is not None:
        reputation_section = f'''<section class="reputation">
          <div class="wrap reputation-grid">
            <div>
              <div class="section-kicker">Reviews</div>
              <h2>What {copy["audience"]} say about {business_name}.</h2>
              <p><strong>{business_name}</strong> holds <strong>{float(rating):.1f} stars</strong> across <strong>{int(review_count):,} Google reviews</strong>.</p>
              {reviews_link}
            </div>
            <div class="rating-panel"><div class="big-rating">{float(rating):.1f}</div><div class="stars" aria-label="{float(rating):.1f} out of 5">{stars}</div><strong>{int(review_count):,} Google reviews</strong></div>
          </div>
        </section>'''

    reviews_nav = '<a href="#reviews">Reviews</a>' if review_cards else ""
    why_cards = []
    if reputation_text:
        why_cards.append(("★", f"Rated on Google", f"{reputation_text}, from real {copy['audience']}."))
    why_cards.append(("⌖", f"Local to {city}", f"Serving {area_names}."))
    why_cards.append((
        "☎" if phone else "→",
        "Easy to reach",
        f"Call {phone} to talk through what you need." if phone
        else "Get in touch to talk through what you need.",
    ))
    why_markup = "".join(
        f'<article class="why-card"><b>{mark}</b><h3>{title}</h3><p>{text}</p></article>'
        for mark, title, text in why_cards
    )

    about_points = [
        ("Where we work", f"{location or city} and nearby communities"),
        (f"{unit.capitalize()}s", ", ".join(_safe(item) for item in services[:3])),
    ]
    if reputation_text:
        about_points.append(("Google reviews", _safe(reputation_text)))
    if phone:
        about_points.append(("Talk to us", phone))
    about_markup = "".join(
        f'<div class="about-point"><strong>{label}</strong><span>{value}</span></div>'
        for label, value in about_points
    )

    footer_services = "".join(f"<li>{_safe(item)}</li>" for item in services[:6])
    footer_areas = "".join(f"<li>{_safe(item)}</li>" for item in service_areas[:6])
    footer_rating = f'<p class="footer-rating">{stars} {_safe(reputation_text)}</p>' if reputation_text else ""
    footer_phone = f'<a class="footer-phone" href="{call_href}">{phone}</a>' if phone else ""

    faq_items = [
        (
            f"What areas does {business_name_raw} serve?",
            f"{business_name_raw} serves {', '.join(service_areas[:5])}. Get in touch to confirm your location.",
        ),
        (
            f"What services does {business_name_raw} offer?",
            f"{business_name_raw} offers {', '.join(services[:4])}. Get in touch to confirm the details for your {engagement}.",
        ),
        (
            f"How do I get started?",
            f"Call {phone_raw or business_name_raw} directly to discuss your {engagement}, confirm availability, and determine the next step.",
        ),
        (
            f"Can I ask about a {unit} that is not listed here?",
            f"Yes. Contact the business directly to ask about other {unit}s or special requests.",
        ),
    ]
    faq_markup = "".join(
        f'<details><summary>{_safe(question)}</summary><p>{_safe(answer)}</p></details>'
        for question, answer in faq_items
    )

    schema_json = _schema_json(source, services, service_areas)

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow,noarchive" />
  <meta name="referrer" content="no-referrer" />
  <meta name="description" content="{business_name}, {category_lower} in {location}. See {unit}s, areas served, reviews and how to get in touch." />
  <title>{business_name} | {category} in {location}</title>
  <script type="application/ld+json">{schema_json}</script>
  <style>
    :root{{--ink:{palette['ink']};--accent:{palette['accent']};--surface:{palette['surface']};--paper:#fff;--muted:#647078;--line:#dfe4e7;--dark:#0b1720}}
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff;line-height:1.55}}a{{color:inherit;text-decoration:none}}img{{display:block;max-width:100%}}.wrap{{width:min(1180px,calc(100% - 40px));margin:0 auto}}
    .concept{{background:#08121a;color:#bac5ca;text-align:center;font-size:12px;padding:8px 14px}}
    header{{position:absolute;z-index:10;left:0;right:0;color:#fff;padding:24px 0}}.nav{{display:flex;align-items:center;justify-content:space-between;gap:24px}}.brand{{font-size:26px;font-weight:850;letter-spacing:-.035em;line-height:1.15}}.nav-links{{display:flex;align-items:center;gap:30px;font-size:17px;font-weight:600;white-space:nowrap}}.nav-links a{{opacity:.92}}.nav-call{{border:0;padding:13px 20px;border-radius:9px;font-size:17px;font-weight:800;background:var(--accent);color:#101820;opacity:1!important}}
    .hero{{position:relative;min-height:720px;overflow:hidden;background:linear-gradient(120deg,var(--ink) 0%,#1b3346 72%,#3e4c55 100%);color:#fff;display:grid;align-items:end;padding:158px 0 80px}}.hero-photo{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.hero.has-photo:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,17,28,.82),rgba(8,25,39,.58) 45%,rgba(8,25,39,.08) 80%)}}.hero.has-photo h1,.hero.has-photo .hero-copy{{text-shadow:0 1px 18px rgba(0,0,0,.45)}}.hero:not(.has-photo):after{{content:"";position:absolute;inset:0;background:radial-gradient(circle at 82% 24%,color-mix(in srgb,var(--accent) 32%,transparent),transparent 25%)}}.hero-grid{{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.55fr);gap:58px;align-items:end}}.eyebrow,.section-kicker{{font-size:11px;font-weight:850;letter-spacing:.17em;text-transform:uppercase;color:var(--accent)}}h1{{font-size:clamp(48px,6.5vw,82px);line-height:.98;letter-spacing:-.055em;margin:15px 0 22px;max-width:850px}}.hero-copy{{font-size:18px;line-height:1.7;color:#e4eaee;max-width:680px;margin:0}}.actions{{display:flex;gap:11px;flex-wrap:wrap;margin-top:29px}}.button{{display:inline-flex;align-items:center;justify-content:center;padding:13px 18px;border-radius:8px;font-weight:850;font-size:14px}}.button-primary{{background:var(--accent);color:#101820}}.button-secondary{{border:1px solid #ffffff55;background:#ffffff0c}}.proof-card{{border:1px solid #ffffff2d;background:#ffffff12;backdrop-filter:blur(12px);padding:23px;border-radius:14px}}.stars{{color:var(--accent);letter-spacing:.08em}}.proof-card strong{{display:block;font-size:20px;margin-top:8px}}.proof-card span{{display:block;color:#cbd4d9;font-size:12px;margin-top:4px}}
    .trust-bar{{position:relative;z-index:4;margin-top:-28px}}.trust-grid{{display:grid;grid-template-columns:1.25fr .75fr .75fr .85fr;background:#fff;border:1px solid var(--line);box-shadow:0 18px 45px #10203012}}.trust-cell{{padding:22px 25px;border-left:1px solid var(--line)}}.trust-cell:first-child{{border-left:0}}.trust-cell strong{{display:block;font-size:18px;letter-spacing:-.02em}}.trust-cell span{{font-size:12px;color:var(--muted)}}
    section{{padding:82px 0}}.section-head{{display:flex;align-items:end;justify-content:space-between;gap:36px;margin-bottom:34px}}.section-head h2,.about-copy h2,.why h2,.process h2,.reputation h2,.areas h2,.faq h2,.contact h2{{font-size:clamp(36px,4.3vw,54px);line-height:1.02;letter-spacing:-.047em;margin:8px 0 0}}.section-head p{{max-width:480px;margin:0;color:var(--muted)}}
    .services{{background:var(--surface)}}.service-grid{{display:grid;grid-template-columns:repeat(var(--cols,3),1fr);gap:14px}}.service-card{{background:#fff;border:1px solid var(--line);padding:25px;min-height:225px;display:flex;flex-direction:column}}.service-icon{{font-size:11px;font-weight:850;color:#9a6c13}}.service-card h3{{font-size:22px;line-height:1.15;letter-spacing:-.035em;margin:24px 0 10px}}.service-card p{{font-size:13px;color:var(--muted);margin:0 0 25px}}.service-card a{{margin-top:auto;font-size:12px;font-weight:850;color:#4d5a62}}.service-card a span{{color:#9a6c13}}
    .about-grid{{display:grid;grid-template-columns:{'1fr 1fr' if media else '1fr'};gap:58px;align-items:center}}.about-photo{{width:100%;height:500px;object-fit:cover;border-radius:16px;box-shadow:0 20px 50px #10203018}}.about-copy p{{font-size:16px;color:var(--muted);max-width:650px}}.about-points{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:28px}}.about-point{{border:1px solid var(--line);padding:18px;border-radius:10px}}.about-point strong{{display:block;font-size:14px}}.about-point span{{display:block;color:var(--muted);font-size:12px;margin-top:5px}}
    .why{{background:var(--dark);color:#fff}}.why h2{{max-width:760px}}.why-grid{{display:grid;grid-template-columns:repeat(var(--cols,3),1fr);gap:14px;margin-top:36px}}.why-card{{border:1px solid #ffffff22;background:#ffffff08;padding:26px;border-radius:12px}}.why-card b{{display:grid;place-items:center;width:34px;height:34px;border-radius:999px;background:var(--accent);color:#111;font-weight:700}}.why-card h3{{font-size:20px;margin:22px 0 9px}}.why-card p{{color:#bcc7cd;font-size:13px;margin:0}}
    .process-grid{{display:grid;grid-template-columns:.8fr 1.2fr;gap:60px;align-items:start}}.steps{{display:grid;gap:0;border-top:1px solid var(--line)}}.step{{display:grid;grid-template-columns:56px 1fr;gap:18px;padding:24px 0;border-bottom:1px solid var(--line)}}.step-number{{font-weight:850;color:#9a6c13}}.step h3{{margin:0 0 6px;font-size:20px}}.step p{{margin:0;color:var(--muted);font-size:13px}}
    .mid-cta{{padding:0 0 82px}}.mid-cta-card{{display:flex;align-items:center;justify-content:space-between;gap:32px;padding:34px 38px;border-radius:16px;background:var(--ink);color:#fff}}.mid-cta-card strong{{display:block;font-size:28px;line-height:1.1;letter-spacing:-.035em}}.mid-cta-card span{{display:block;color:#cbd4d9;margin-top:7px;font-size:13px}}.mid-cta-card .button{{background:var(--accent);color:#101820;white-space:nowrap}}
    .reputation{{position:relative;overflow:hidden;background:var(--surface)}}.reputation-grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:58px;align-items:center}}.reputation p{{font-size:16px;color:var(--muted);max-width:700px}}.rating-panel{{background:#fff;border:1px solid var(--line);padding:38px;border-radius:16px;text-align:center;box-shadow:0 24px 60px #10203014}}.big-rating{{font-size:78px;line-height:1;font-weight:900;letter-spacing:-.06em}}.rating-panel strong,.rating-panel span{{display:block}}.rating-panel strong{{margin-top:12px;font-size:17px}}.rating-panel span{{font-size:12px;color:var(--muted);margin-top:5px}}
    .reviews-head{{display:flex;align-items:end;justify-content:space-between;gap:40px;margin-bottom:34px}}.reviews-summary{{display:flex;align-items:center;gap:14px;flex:none}}.reviews-summary strong{{font-size:58px;line-height:1;font-weight:900;letter-spacing:-.05em}}.reviews-summary span{{font-size:13px;color:var(--muted)}}.reviews-summary .stars{{color:#f5a623;font-size:19px;letter-spacing:.06em}}.review-grid{{display:grid;grid-template-columns:repeat(var(--cols,3),minmax(0,1fr));gap:16px}}.review-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px;display:flex;flex-direction:column;box-shadow:0 14px 34px #10203010}}.review-stars{{color:#f5a623;font-size:18px;letter-spacing:.06em}}.review-card p{{flex:1;margin:14px 0 22px;font-size:15px;line-height:1.65;color:var(--ink)}}.review-card footer{{display:flex;align-items:center;gap:12px;border-top:1px solid var(--line);padding-top:16px}}.review-avatar{{position:relative;flex:none;width:42px;height:42px;border-radius:50%;overflow:hidden;display:grid;place-items:center;background:var(--ink);color:#fff;font-weight:800}}.review-avatar img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.review-meta{{min-width:0}}.review-meta strong{{display:block;font-size:14px}}.review-meta small{{display:block;margin-top:2px;font-size:12px;color:var(--muted)}}.review-meta small a{{text-decoration:underline}}.reviews-more{{margin:26px 0 0}}
    .photo-band{{padding:0;height:430px;overflow:hidden;background:#dfe5e8}}.photo-band img{{width:100%;height:100%;object-fit:cover}}
    .areas{{background:#0d1a24;color:#fff}}.areas-grid{{display:grid;grid-template-columns:.82fr 1.18fr;gap:60px;align-items:center}}.areas p{{color:#bdc7cc}}.areas ul{{display:flex;flex-wrap:wrap;gap:10px;list-style:none;padding:0;margin:0}}.areas li{{border:1px solid #ffffff24;background:#ffffff0b;padding:10px 14px;border-radius:999px;font-size:13px}}
    .faq-grid{{display:grid;grid-template-columns:.72fr 1.28fr;gap:60px;align-items:start}}.faq p{{color:var(--muted)}}details{{border-top:1px solid var(--line);padding:18px 0}}details:last-child{{border-bottom:1px solid var(--line)}}summary{{cursor:pointer;font-weight:800;font-size:16px;list-style:none;display:flex;justify-content:space-between;gap:20px}}summary:after{{content:"+";color:#9a6c13}}details[open] summary:after{{content:"–"}}details p{{margin:10px 36px 0 0!important;font-size:13px}}
    .contact{{background:var(--accent);padding:68px 0}}.contact-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:60px;align-items:center}}.contact h2{{max-width:760px}}.contact p{{max-width:650px;margin:14px 0 0;color:#27323a}}.contact-card{{background:#0d1a24;color:#fff;padding:28px;border-radius:14px}}.contact-card span{{display:block;color:#b9c4ca;font-size:12px}}.contact-card strong{{display:block;font-size:25px;margin:6px 0 18px}}.contact-card .button{{width:100%;background:#fff;color:#0d1a24}}
    .text-link{{color:var(--ink);font-weight:800;border-bottom:2px solid var(--accent)}}
    .site-footer{{background:var(--dark);color:#c6d0d5;padding:64px 0 28px;font-size:14px}}.footer-top{{display:grid;grid-template-columns:1.5fr 1fr 1fr 1fr;gap:40px}}.footer-brand strong{{display:block;color:#fff;font-size:20px;letter-spacing:-.02em}}.footer-brand p{{margin:8px 0 0}}.footer-rating{{color:#fff}}.footer-phone{{display:inline-block;margin-top:14px;color:#fff;font-size:20px;font-weight:800}}.site-footer h4{{margin:0 0 14px;color:#fff;font-size:12px;letter-spacing:.14em;text-transform:uppercase}}.site-footer ul{{list-style:none;margin:0;padding:0;display:grid;gap:9px}}.footer-base{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:44px;padding-top:22px;border-top:1px solid #ffffff1f;font-size:12px;color:#93a1a9}}.mobile-call{{display:none;position:fixed;z-index:30;left:12px;right:12px;bottom:12px;background:var(--accent);color:#111820;padding:14px;border-radius:10px;text-align:center;font-weight:850;box-shadow:0 18px 45px #0005}}
    @media(max-width:1080px){{.nav-links a:not(.nav-call){{display:none}}}}
    @media(max-width:840px){{.brand{{font-size:20px}}.nav-call{{font-size:15px;padding:11px 14px}}.reviews-head{{display:block}}.reviews-summary{{margin-top:20px}}.review-grid{{grid-template-columns:1fr}}.wrap{{width:min(100% - 28px,1180px)}}.nav-links a:not(.nav-call){{display:none}}.hero{{min-height:650px;padding:125px 0 58px}}.hero-grid,.about-grid,.process-grid,.reputation-grid,.areas-grid,.faq-grid,.contact-grid{{grid-template-columns:1fr;gap:32px}}.hero-grid{{gap:28px}}.proof-card{{max-width:360px}}.hero.has-photo:after{{background:linear-gradient(180deg,rgba(6,18,30,.5),rgba(6,18,30,.82) 70%)}}.trust-grid{{grid-template-columns:1fr 1fr}}.trust-cell:nth-child(3){{border-left:0;border-top:1px solid var(--line)}}.trust-cell:nth-child(4){{border-top:1px solid var(--line)}}section{{padding:64px 0}}.section-head{{display:block}}.section-head p{{margin-top:16px}}.service-grid,.why-grid{{grid-template-columns:1fr}}.footer-top{{grid-template-columns:1fr 1fr;gap:32px}}.footer-brand{{grid-column:1/-1}}.about-points{{grid-template-columns:1fr}}.about-photo{{height:360px}}.mid-cta-card{{display:block;padding:28px}}.mid-cta-card .button{{margin-top:22px;width:100%}}.photo-band{{height:300px}}.mobile-call{{display:block}}.site-footer{{padding-bottom:96px}}.site-footer .button{{white-space:nowrap}}}}
  </style>
</head>
<body>
  <div class="concept">Concept website prepared by Lilos Growth for demonstration purposes. Not affiliated with or endorsed by {business_name}.</div>
  <header><div class="wrap nav"><div class="brand">{business_name}</div><nav class="nav-links"><a href="#services">{_safe(unit.capitalize())}s</a><a href="#about">About</a>{reviews_nav}<a href="#areas">Areas served</a><a href="#faq">FAQ</a><a class="nav-call" href="{call_href}">{call_label}</a></nav></div></header>
  <main>
    <section class="{hero_class}">{hero_photo}<div class="wrap hero-grid"><div><div class="eyebrow">{category} · {location}</div><h1>{headline}</h1><p class="hero-copy">{subheadline}</p><div class="actions"><a class="button button-primary" href="{call_href}">{call_label}</a><a class="button button-secondary" href="#services">View {_safe(unit)}s</a></div></div>{proof_card}</div></section>
    <div class="trust-bar"><div class="wrap trust-grid"><div class="trust-cell"><strong>{business_name}</strong><span>{category} serving {area_names}</span></div><div class="trust-cell">{rating_stat}</div><div class="trust-cell">{review_stat}</div><div class="trust-cell"><strong>{len(service_areas[:8])}</strong><span>Areas served</span></div></div></div>
    <section id="services" class="services"><div class="wrap"><div class="section-head"><div><div class="section-kicker">{_safe(unit.capitalize())}s</div><h2>{unit.capitalize()}s in {city}</h2></div><p>What {business_name} can help with. Don't see what you need? Ask.</p></div><div class="service-grid" style="--cols:{min(len(services[:6]), 3)}">{service_cards}</div></div></section>
    <section id="about"><div class="wrap about-grid">{media}<div class="about-copy"><div class="section-kicker">About</div><h2>{business_name}, serving {city} and nearby communities.</h2><p>{business_name} works with {copy["audience"]} across {area_names}. Here's the short version of what to expect.</p><div class="about-points">{about_markup}</div></div></div></section>
    <section class="why"><div class="wrap"><div class="section-kicker">Why {business_name}</div><h2>Why {copy["audience"]} in {city} choose {business_name}.</h2><div class="why-grid" style="--cols:{len(why_cards)}">{why_markup}</div></div></section>
    <section class="process"><div class="wrap process-grid"><div><div class="section-kicker">Getting started</div><h2>How it works.</h2></div><div class="steps"><div class="step"><div class="step-number">01</div><div><h3>{copy["start"]}</h3><p>Start with the {unit}s above, or call to ask about anything not listed.</p></div></div><div class="step"><div class="step-number">02</div><div><h3>Share the details</h3><p>{copy["details"]}</p></div></div><div class="step"><div class="step-number">03</div><div><h3>Get your next step</h3><p>{business_name} will confirm timing and what happens next.</p></div></div></div></div></section>
    <section class="mid-cta"><div class="wrap"><div class="mid-cta-card"><div><strong>Ready to get started?</strong><span>Contact {business_name} to confirm availability and discuss the next step.</span></div><a class="button" href="{call_href}">{call_label}</a></div></div></section>
    {reputation_section}
    {photo_band}
    <section id="areas" class="areas"><div class="wrap areas-grid"><div><div class="section-kicker">Areas served</div><h2>Serving {city} and nearby communities.</h2><p>Not sure if you're covered? Get in touch and ask.</p></div><ul>{area_chips}</ul></div></section>
    <section id="faq" class="faq"><div class="wrap faq-grid"><div><div class="section-kicker">Frequently asked questions</div><h2>Quick answers before you call.</h2></div><div>{faq_markup}</div></div></section>
    <section id="contact" class="contact"><div class="wrap contact-grid"><div><div class="section-kicker" style="color:#26313a">Contact</div><h2>Looking for a {category_lower} in {city}?</h2><p>Talk to {business_name} directly about your {engagement} and what happens next.</p></div><div class="contact-card"><span>Talk to us</span><strong>{phone or business_name}</strong><a class="button" href="{call_href}">{call_label}</a></div></div></section>
  </main>
  <footer class="site-footer"><div class="wrap footer-top"><div class="footer-brand"><strong>{business_name}</strong><p>{category} in {location or city}</p>{footer_rating}{footer_phone}</div><div><h4>{_safe(unit.capitalize())}s</h4><ul>{footer_services}</ul></div><div><h4>Areas served</h4><ul>{footer_areas}</ul></div><div><h4>Get in touch</h4><a class="button button-primary" href="{call_href}">{call_label}</a></div></div><div class="wrap footer-base"><span>© {date.today().year} {business_name}</span><span>Concept website by Lilos Growth. Not affiliated with or endorsed by {business_name}.</span></div></footer>
  {f'<a class="mobile-call" href="{call_href}">{call_label}</a>' if phone else ''}
</body>
</html>'''
