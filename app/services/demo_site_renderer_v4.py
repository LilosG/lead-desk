"""v4 demo homepage: three styles, brand-aware colour, real listing details.

Facts on the page come only from the prospect's Google listing, its reviews,
its own website and what the operator confirmed in the builder. Nothing here
states licences, years in business, guarantees, prices or response times.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import escape
from typing import Any
from urllib.parse import quote_plus

from app.services.demo_design import STYLES, design_tokens, icon_svg, icon_name
from app.services.demo_service_copy import describe_service
from app.services.demo_site_renderer_v3 import niche_copy, star_string

V4_KEY = "premium-v4"
V4_TEMPLATE_OPTIONS = [
    {
        "key": V4_KEY,
        "name": "Premium homepage (recommended)",
        "description": (
            "Polished one-page homepage with a style picked for the niche, the business's own logo and "
            "brand colour when its site has them, real hours, map and reviews."
        ),
    },
    *(
        {
            "key": f"{V4_KEY}-{style}",
            "name": f"Premium homepage: {STYLES[style]['label']} style",
            "description": description,
        }
        for style, description in (
            ("bold", "Full-width photo hero and strong type. Built for trades and auto."),
            ("clean", "Light split hero with a framed photo. Suits dental, legal and most offices."),
            ("soft", "Airy serif look with an arched photo. Suits med spas, wellness and real estate."),
        )
    ),
]
V4_KEYS = {option["key"] for option in V4_TEMPLATE_OPTIONS}


def style_override(template_key: str) -> str | None:
    suffix = template_key.removeprefix(f"{V4_KEY}-")
    return suffix if suffix != template_key and suffix in STYLES else None


_DAY_SHORT = {
    "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu",
    "friday": "Fri", "saturday": "Sat", "sunday": "Sun",
}


def hours_rows(hours: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Google's weekday lines grouped into ranges: [("Mon–Fri", "7:00 AM – 5:00 PM"), ...]."""
    lines = (hours or {}).get("weekdayDescriptions") or []
    days: list[tuple[str, str]] = []
    for line in lines:
        if not isinstance(line, str) or ":" not in line:
            continue
        day, value = line.split(":", 1)
        short = _DAY_SHORT.get(day.strip().lower())
        if short:
            days.append((short, " ".join(value.replace(" ", " ").replace(" ", " ").split())))
    if len(days) != 7:
        return []
    rows: list[tuple[str, str]] = []
    start = 0
    for index in range(1, 8):
        if index == 7 or days[index][1] != days[start][1]:
            label = days[start][0] if index - 1 == start else f"{days[start][0]}–{days[index - 1][0]}"
            rows.append((label, days[start][1]))
            start = index
    return rows


def hours_summary(rows: list[tuple[str, str]]) -> str | None:
    """A short line for the stats strip, e.g. "Open 7 days" or "Mon–Fri"."""
    if not rows:
        return None
    if len(rows) == 1 and "24 hours" in rows[0][1].lower():
        return "Open 24/7"
    days: list[bool] = []
    for label, value in rows:
        first, _, last = label.partition("–")
        names = list(_DAY_SHORT.values())
        span = names.index(last or first) - names.index(first) + 1
        days.extend([value.lower() != "closed"] * span)
    open_days = [name for name, is_open in zip(_DAY_SHORT.values(), days) if is_open]
    if not open_days:
        return None
    if len(open_days) == 7:
        return "Open 7 days"
    first_open = days.index(True)
    last_open = len(days) - 1 - days[::-1].index(True)
    if all(days[first_open:last_open + 1]):
        return f"Open {open_days[0]}–{open_days[-1]}" if len(open_days) > 1 else f"Open {open_days[0]}"
    return f"Open {len(open_days)} days a week"


def _safe(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _phone_href(phone: str | None) -> str:
    if not phone:
        return "#contact"
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return f"tel:{digits}" if digits else "#contact"


def _join(items: list[str], limit: int) -> str:
    items = items[:limit]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _lower_phrase(text: str) -> str:
    """Lowercase a service name for use mid-sentence, keeping acronyms and brands (EV, Botox)."""
    if len(text.split()) == 1:
        return text
    return " ".join(
        word if (word.isupper() and len(word) > 1) or any(ch.isupper() for ch in word[1:]) else word.lower()
        for word in text.split()
    )


def _quote_excerpt(text: str, limit: int = 260, floor: int = 140) -> str:
    """A review quote cut at a sentence end when one falls in a good range."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", window) if m.end() >= floor]
    if ends:
        return window[:ends[-1]]
    return _excerpt(text, limit)


def _lead_form(form_id: str, *, title: str, button: str, services: list[str], unit: str, dark: bool = False) -> str:
    """A concept enquiry form. It never sends anything; submitting shows a note instead."""
    options = "".join(f"<option>{_safe(s)}</option>" for s in services[:6])
    return (
        f'<form class="lead-form{" on-dark" if dark else ""}" id="{form_id}" action="#" autocomplete="off">'
        f'<h3>{_safe(title)}</h3><p class="form-sub">Leave your details and get a call back.</p>'
        f'<label>Name<input name="name" type="text" required placeholder="Your name" /></label>'
        f'<label>Phone<input name="phone" type="tel" required placeholder="(555) 555-5555" /></label>'
        f'<label>{_safe(unit.capitalize())} needed<select name="service">{options}<option>Something else</option></select></label>'
        f'<label>Details <span>(optional)</span><textarea name="details" rows="3" placeholder="A few words about what you need"></textarea></label>'
        f'<button class="btn btn-accent" type="submit">{_safe(button)}</button>'
        f'<p class="form-note" hidden>This is a concept website, so nothing was sent. On the live site, this request would go straight to the business.</p>'
        f'</form>'
    )


def _area_line(index: int, town: str, services: list[str], audience: str, category: str) -> str:
    """One line per town, rotating wording and services so the cards don't read as copies."""
    picks = list(dict.fromkeys(services[(index + offset) % len(services)] for offset in range(min(2, len(services)))))
    first = _lower_phrase(picks[0])
    second = _lower_phrase(picks[1]) if len(picks) > 1 else None
    if second is None:
        return f"{first[:1].upper() + first[1:]} for {audience} in {town}."
    lines = (
        f"{first[:1].upper() + first[1:]} and {second} for {audience} in {town}.",
        f"Help across {town}, from {first} to {second}.",
        f"Serving {town} {audience} with {first}, {second} and more.",
    )
    return lines[index % len(lines)]


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def _schema_json(source: dict[str, Any], services: list[str], areas: list[str], address: str | None) -> str:
    schema: dict[str, Any] = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": source.get("name")}
    if source.get("phone"):
        schema["telephone"] = source["phone"]
    if address:
        schema["address"] = address
    if areas:
        schema["areaServed"] = [{"@type": "City", "name": area} for area in areas[:8]]
    if services:
        schema["knowsAbout"] = services[:6]
    # No aggregateRating: Google reviews can't be marked up as the business's own.
    return json.dumps(schema, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


def _review_cards(reviews: list[dict[str, Any]]) -> list[dict[str, str]]:
    cards = []
    for review in reviews:
        author = str(review.get("author") or "").strip()
        text = " ".join(str(review.get("text") or "").split())
        if not author or not text:
            continue
        cards.append({
            "author": author,
            "initial": author[:1].upper(),
            "photo": str(review.get("author_photo") or ""),
            "author_url": str(review.get("author_url") or ""),
            "url": str(review.get("url") or ""),
            "date": str(review.get("date") or ""),
            "rating": str(int(review.get("rating") or 5)),
            "text": text,
        })
    return cards


def render_demo_site_v4(*, source: dict[str, Any], content: dict[str, Any], brand: dict[str, Any]) -> str:
    style = brand.get("style") if brand.get("style") in STYLES else "clean"
    spec = STYLES[style]
    tokens = design_tokens(brand.get("palette") or {})
    copy = niche_copy(source.get("niche_profile"))
    profile = source.get("niche_profile")
    unit, engagement, audience = copy["unit"], copy["engagement"], copy["audience"]

    name_raw = str(source.get("name") or "Local Business")
    name = _safe(name_raw)
    city_raw = str(source.get("city") or "your area")
    city = _safe(city_raw)
    state = _safe(source.get("state"))
    location = ", ".join(part for part in (city, state) if part)
    category_raw = str(source.get("primary_type_display") or "Local Business")
    category_lower = _safe(category_raw.lower())
    phone_raw = source.get("phone")
    phone = _safe(phone_raw)
    call_href = _safe(_phone_href(phone_raw))
    cta_label = f"Call {phone}" if phone else _safe(copy["cta"])
    rating = source.get("rating")
    review_count = source.get("review_count")
    stars = star_string(rating)
    street = str(source.get("street") or "").strip()
    address_raw = str(source.get("address") or "").strip() if street else ""
    address = _safe(address_raw)
    hours = hours_rows(source.get("hours"))
    open_line = hours_summary(hours)
    maps_url = _safe(source.get("google_maps_uri"))

    services = [str(s).strip() for s in content.get("services", []) if str(s).strip()] or [category_raw]
    areas = [str(a).strip() for a in content.get("service_areas", []) if str(a).strip()] or [city_raw]
    blurbs = content.get("service_blurbs") if isinstance(content.get("service_blurbs"), dict) else {}

    headline = _safe(content.get("headline") or f"{category_raw} in {city_raw}")
    subheadline = _safe(
        content.get("subheadline")
        or f"{name_raw} works with {audience} across {city_raw} and nearby communities."
    )
    hero_image = _safe(content.get("hero_image_url"))
    work_image = _safe(content.get("work_image_url"))
    secondary_image = _safe(content.get("secondary_image_url"))
    feature_image = work_image or secondary_image

    has_rating = rating is not None and review_count is not None
    rating_text = f"{float(rating):.1f}" if rating is not None else ""
    reviews_text = f"{int(review_count):,}" if review_count is not None else ""

    # --- header ---------------------------------------------------------------
    logo_url = _safe(brand.get("logo_url"))
    if logo_url:
        chip = "logo-chip dark" if brand.get("logo_on_dark") else "logo-chip"
        brand_mark = f'<a class="{chip}" href="#top"><img src="{logo_url}" alt="{name}" /></a>'
    else:
        brand_mark = f'<a class="wordmark" href="#top">{name}</a>'
    review_cards = _review_cards(source.get("reviews") or [])
    nav_links = [
        ("#services", f"{unit.capitalize()}s"),
        ("#about", "About"),
        *([("#reviews", "Reviews")] if review_cards or has_rating else []),
        ("#areas", "Areas"),
        ("#contact", "Contact"),
    ]
    nav = "".join(f'<a href="{href}">{_safe(label)}</a>' for href, label in nav_links)
    header = (
        f'<header class="site-header"><div class="wrap nav">{brand_mark}'
        f'<nav class="nav-links">{nav}</nav><a class="btn btn-accent nav-cta" href="{call_href}">{cta_label}</a></div></header>'
    )

    # --- hero -----------------------------------------------------------------
    proof = ""
    if has_rating:
        proof = (
            f'<div class="proof"><span class="proof-stars" aria-label="{rating_text} out of 5">{stars}</span>'
            f'<strong>{rating_text}</strong><span>from {reviews_text} Google reviews</span></div>'
        )
    actions = (
        f'<div class="actions"><a class="btn btn-accent btn-lg" href="{call_href}">{cta_label}</a>'
        f'<a class="btn btn-ghost btn-lg" href="#services">See {_safe(unit)}s</a></div>'
    )
    eyebrow = f'<div class="eyebrow">{_safe(category_raw)} · {location or city}</div>'
    if style == "bold":
        photo = f'<img class="hero-bg" src="{hero_image}" alt="" loading="eager" />' if hero_image else ""
        hero = (
            f'<section class="hero hero-bold{" has-photo" if hero_image else ""}" id="top">{photo}'
            f'{header}<div class="wrap hero-inner"><div class="hero-copy">{eyebrow}<h1>{headline}</h1>'
            f'<p class="lead">{subheadline}</p>{actions}</div>'
            f'<div class="hero-form">{_lead_form("hero-form", title=copy["cta"], button=copy["cta"], services=services, unit=unit)}</div>'
            f'</div></section>'
        )
    else:
        if hero_image:
            visual = f'<div class="hero-visual"><img src="{hero_image}" alt="{name}, {category_lower}" loading="eager" />{proof}</div>'
        else:
            visual = (
                f'<div class="hero-visual hero-panel"><div class="panel-icon">{icon_svg(icon_name(services[0]), size=40)}</div>'
                f'<strong>{_safe(services[0])}</strong><span>{location or city}</span>{proof}</div>'
            )
        hero = (
            f'{header}<section class="hero hero-split" id="top"><div class="wrap hero-inner">'
            f'<div class="hero-copy">{eyebrow}<h1>{headline}</h1><p class="lead">{subheadline}</p>{actions}</div>'
            f'{visual}</div></section>'
        )

    # --- stats strip ----------------------------------------------------------
    stats: list[tuple[str, str]] = []
    if rating_text:
        stats.append((f'{rating_text}<small>★</small>', "Google rating"))
    if reviews_text:
        stats.append((reviews_text, "Google reviews"))
    if len(areas) > 1:
        stats.append((str(len(areas[:8])), "Towns served"))
    if open_line:
        stats.append((_safe(open_line.removeprefix("Open ")), "Open"))
    if len(stats) < 4:
        stats.append((str(len(services[:6])), f"{unit.capitalize()}s"))
    stats = stats[:4]
    stats_markup = "".join(f'<div class="stat"><strong>{value}</strong><span>{label}</span></div>' for value, label in stats)
    # A lone "6 services" box says nothing; the strip only shows with real facts.
    stats_strip = (
        f'<div class="stats-wrap"><div class="wrap stats" style="--n:{len(stats)}">{stats_markup}</div></div>'
        if len(stats) >= 2 else '<div class="stats-spacer"></div>'
    )

    # --- services -------------------------------------------------------------
    cards = []
    for index, service in enumerate(services[:6]):
        blurb = blurbs.get(service) or describe_service(service, index, unit, profile)
        cards.append(
            f'<article class="card service"><div class="icon">{icon_svg(icon_name(service))}</div>'
            f'<h3>{_safe(service)}</h3><p>{_safe(blurb)}</p>'
            f'<a class="more" href="{call_href}">Ask about this {_safe(unit)} <span aria-hidden="true">→</span></a></article>'
        )
    cols = 3 if len(cards) >= 3 else len(cards)
    services_section = (
        f'<section class="section" id="services"><div class="wrap"><div class="head">'
        f'<div><div class="kicker">{_safe(unit.capitalize())}s</div><h2>{_safe(category_raw)} {_safe(unit)}s in {city}</h2></div>'
        f'<p>Here’s what {name} can help with. Don’t see what you need? Just ask.</p></div>'
        f'<div class="grid services-grid" style="--cols:{cols}">{"".join(cards)}</div></div></section>'
    )

    # --- about ----------------------------------------------------------------
    about_text = content.get("about") or (
        f"{name_raw} is {_article(category_raw)} {category_raw.lower()} serving {_join(areas, 4)}. "
        f"Whether you need {_join([_lower_phrase(s) for s in services[:3]], 3)}"
        f" or something else, start with a quick call to talk through your {engagement}."
    )
    points = [f"Serving {_join(areas, 4)}"]
    if has_rating:
        points.append(f"Rated {rating_text} by {reviews_text} {audience} on Google")
    if open_line:
        points.append(open_line)
    points.append(f"Call {phone_raw} to get started" if phone_raw else f"{copy['cta']} to get started")
    point_markup = "".join(f'<li>{icon_svg("check", size=20)}<span>{_safe(p)}</span></li>' for p in points)
    if feature_image:
        about_visual = f'<div class="about-visual"><img src="{feature_image}" alt="{name} at work" loading="lazy" /></div>'
    else:
        tiles = "".join(
            f'<div class="tile"><span>{icon_svg(icon_name(s), size=28)}</span><b>{_safe(s)}</b></div>'
            for s in services[:6]
        )
        about_visual = f'<div class="about-visual about-panel"><div class="tiles">{tiles}</div></div>'
    about_section = (
        f'<section class="section alt" id="about"><div class="wrap split">{about_visual}'
        f'<div><div class="kicker">About</div><h2>Local {category_lower} for {city} and nearby.</h2>'
        f'<p class="body">{_safe(about_text)}</p><ul class="checks">{point_markup}</ul>'
        f'<a class="btn btn-accent" href="{call_href}">{cta_label}</a></div></div></section>'
    )

    # --- reviews --------------------------------------------------------------
    reviews_section = ""
    if review_cards and has_rating:
        feature, rest = review_cards[0], review_cards[1:3]

        def who(card: dict[str, str]) -> str:
            avatar = f'<img src="{_safe(card["photo"])}" alt="" loading="lazy" referrerpolicy="no-referrer" />' if card["photo"] else ""
            author = (
                f'<a href="{_safe(card["author_url"])}" target="_blank" rel="noopener">{_safe(card["author"])}</a>'
                if card["author_url"] else _safe(card["author"])
            )
            posted = (
                f'<a href="{_safe(card["url"])}" target="_blank" rel="noopener">Google review</a>'
                if card["url"] else "Google review"
            )
            when = f'{_safe(card["date"])} · ' if card["date"] else ""
            return (
                f'<footer><span class="avatar">{_safe(card["initial"])}{avatar}</span>'
                f'<span><strong>{author}</strong><small>{when}{posted}</small></span></footer>'
            )

        rest_markup = "".join(
            f'<article class="card quote"><div class="stars">{star_string(int(c["rating"]))}</div>'
            f'<p>{_safe(_excerpt(c["text"], 260))}</p>{who(c)}</article>'
            for c in rest
        )
        stack = f'<div class="quote-stack">{rest_markup}</div>' if rest else ""
        all_link = (
            f'<a class="text-link" href="{maps_url}" target="_blank" rel="noopener">Read all {reviews_text} reviews on Google →</a>'
            if maps_url else ""
        )
        reviews_section = (
            f'<section class="section" id="reviews"><div class="wrap"><div class="head">'
            f'<div><div class="kicker">Google reviews</div><h2>What {_safe(audience)} say.</h2></div>'
            f'<div class="score"><strong>{rating_text}</strong><span><span class="stars">{stars}</span>{reviews_text} Google reviews</span></div></div>'
            f'<div class="reviews{" solo" if not rest else ""}"><article class="card quote featured"><div class="stars">{star_string(int(feature["rating"]))}</div>'
            f'<blockquote>“{_safe(_quote_excerpt(feature["text"]))}”</blockquote>{who(feature)}</article>'
            f'{stack}</div>'
            f'<p class="after">{all_link}</p></div></section>'
        )
    elif has_rating:
        all_link = (
            f'<a class="text-link" href="{maps_url}" target="_blank" rel="noopener">Read the reviews on Google →</a>'
            if maps_url else ""
        )
        reviews_section = (
            f'<section class="section" id="reviews"><div class="wrap rating-band"><div class="score big">'
            f'<strong>{rating_text}</strong><span><span class="stars">{stars}</span>{reviews_text} Google reviews</span></div>'
            f'<div><h2>Rated {rating_text} by {_safe(audience)} on Google.</h2><p class="body">{all_link}</p></div></div></section>'
        )

    # --- process --------------------------------------------------------------
    steps = [
        (copy["start"], f"Start with the {unit}s above, or call to ask about anything not listed."),
        ("Share the details", copy["details"]),
        ("Get your next step", f"{name_raw} confirms timing and what happens next."),
    ]
    steps_markup = "".join(
        f'<div class="step"><span class="num">{index:02d}</span><h3>{_safe(title)}</h3><p>{_safe(text)}</p></div>'
        for index, (title, text) in enumerate(steps, start=1)
    )
    process_section = (
        f'<section class="section dark"><div class="wrap"><div class="kicker">Getting started</div>'
        f'<h2>Simple from the first call.</h2><div class="steps">{steps_markup}</div></div></section>'
    )

    # --- areas + map ----------------------------------------------------------
    chips = "".join(f'<li>{icon_svg("pin", size=16)}{_safe(a)}</li>' for a in areas[:8])
    map_markup = ""
    if address_raw:
        query = quote_plus(f"{name_raw}, {address_raw}")
        map_markup = (
            f'<div class="map"><iframe title="Map to {name}" loading="lazy" referrerpolicy="no-referrer-when-downgrade" '
            f'src="https://maps.google.com/maps?q={_safe(query)}&amp;z=13&amp;output=embed"></iframe></div>'
        )
    if len(areas) > 1:
        area_cards = "".join(
            f'<article class="area-card"><div class="area-top">{icon_svg("pin", size=18)}<h3>{_safe(category_raw)} in {_safe(town)}</h3></div>'
            f'<p>{_safe(_area_line(index, town, services, audience, category_raw))}</p>'
            f'<a class="more" href="{call_href}">Call about {_safe(town)} <span aria-hidden="true">→</span></a></article>'
            for index, town in enumerate(areas[:6])
        )
        more = areas[6:8]
        more_line = f'<p class="area-more">Also serving {_safe(_join(more, 2))}.</p>' if more else ""
        area_title = (
            f"Serving {_safe(', '.join(areas[:3]))} and nearby." if len(areas) > 3
            else f"Serving {_safe(_join(areas, 3))}."
        )
        areas_section = (
            f'<section class="section alt" id="areas"><div class="wrap"><div class="head"><div>'
            f'<div class="kicker">Areas served</div><h2>{area_title}</h2></div>'
            f'<p>{name} works with {_safe(audience)} across {_safe(_join(areas, 8))}. Not sure if you’re covered? Call and ask.</p></div>'
            f'<div class="areas-layout{" with-map" if map_markup else ""}">{map_markup}'
            f'<div class="area-grid">{area_cards}</div></div>{more_line}</div></section>'
        )
    else:
        areas_section = (
            f'<section class="section alt" id="areas"><div class="wrap {"split" if map_markup else "areas-solo"}">'
            f'<div><div class="kicker">Areas served</div><h2>Serving {city} and nearby communities.</h2>'
            f'<p class="body">Not sure if you’re covered? Call and ask.</p><ul class="chips">{chips}</ul></div>{map_markup}</div></section>'
        )

    # --- faq ------------------------------------------------------------------
    faqs = [
        (f"What areas does {name_raw} serve?", f"{name_raw} serves {_join(areas, 6)}. Call to confirm your location."),
        (f"What {unit}s does {name_raw} offer?", f"{_join(services, 6)}. Ask about anything not listed."),
        ("How do I get started?",
         f"Call {phone_raw} to talk through your {engagement} and the next step." if phone_raw
         else f"Get in touch to talk through your {engagement} and the next step."),
    ]
    if hours:
        faqs.append((f"What are {_possessive(name_raw)} hours?", "; ".join(f"{d}: {v}" for d, v in hours) + "."))
    faq_markup = "".join(f"<details><summary>{_safe(q)}</summary><p>{_safe(a)}</p></details>" for q, a in faqs)
    faq_section = (
        f'<section class="section" id="faq"><div class="wrap split faq-split"><div><div class="kicker">FAQ</div>'
        f'<h2>Quick answers before you call.</h2></div><div class="faq">{faq_markup}</div></div></section>'
    )

    # --- contact --------------------------------------------------------------
    hours_markup = "".join(f"<li><span>{_safe(d)}</span><span>{_safe(v)}</span></li>" for d, v in hours)
    hours_card = (
        f'<div class="hours-card"><h3>{icon_svg("clock", size=20)}Hours</h3><ul>{hours_markup}</ul></div>'
        if hours else ""
    )
    contact_form = _lead_form("contact-form", title=copy["cta"], button=copy["cta"], services=services, unit=unit)
    contact_details = []
    if phone:
        contact_details.append(f'<a class="contact-line" href="{call_href}">{icon_svg("phone", size=20)}<span>{phone}</span></a>')
    if address:
        contact_details.append(f'<div class="contact-line">{icon_svg("pin", size=20)}<span>{address}</span></div>')
    elif location:
        contact_details.append(f'<div class="contact-line">{icon_svg("pin", size=20)}<span>Serving {location}</span></div>')
    contact_section = (
        f'<section class="cta" id="contact"><div class="wrap cta-grid"><div><div class="kicker">Contact</div>'
        f'<h2>Ready when you are.</h2><p>Talk to {name} about your {_safe(engagement)}.</p>'
        f'<div class="contact-lines">{"".join(contact_details)}</div>{hours_card}</div>'
        f'<div class="contact-form">{contact_form}</div></div></section>'
    )

    # --- footer ---------------------------------------------------------------
    foot_rating = f"<p>{stars} {rating_text} · {reviews_text} Google reviews</p>" if has_rating else ""
    foot_phone = f'<a class="foot-phone" href="{call_href}">{phone}</a>' if phone else ""
    foot_services = "".join(f"<li>{_safe(s)}</li>" for s in services[:6])
    foot_areas = "".join(f"<li>{_safe(a)}</li>" for a in areas[:6])
    footer = (
        f'<footer class="site-footer"><div class="wrap foot"><div><strong class="foot-name">{name}</strong>'
        f'<p>{_safe(category_raw)} · {location or city}</p>{foot_rating}{foot_phone}</div>'
        f'<div><h4>{_safe(unit.capitalize())}s</h4><ul>{foot_services}</ul></div>'
        f'<div><h4>Areas</h4><ul>{foot_areas}</ul></div></div>'
        f'<div class="wrap foot-base"><span>© {date.today().year} {name}</span>'
        f'<span>Concept website by Lilos Growth. Not affiliated with or endorsed by {name}.</span></div></footer>'
    )
    mobile_call = f'<a class="mobile-call" href="{call_href}">{cta_label}</a>' if phone else ""

    t = tokens
    css = f"""
:root{{--ink:{t['ink']};--accent:{t['accent']};--surface:{t['surface']};--dark:{t['dark']};--on-accent:{t['on_accent']};--accent-text:{t['accent_text']};--accent-dark:{t['accent_on_dark']};--accent-soft:{t['accent_soft']};--muted:{t['muted']};--line:{t['line']};--muted-dark:{t['muted_on_dark']};--line-dark:{t['line_on_dark']};--hf:"{spec['heading_font']}",ui-sans-serif,system-ui,sans-serif;--bf:"{spec['body_font']}",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--hw:{spec['heading_weight']};--ht:{spec['heading_tracking']};--r:{spec['radius']};--rl:{spec['radius_lg']}}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;font-family:var(--bf);color:var(--ink);background:#fff;line-height:1.6;-webkit-font-smoothing:antialiased}}a{{color:inherit;text-decoration:none}}img{{display:block;max-width:100%}}h1,h2,h3{{font-family:var(--hf);font-weight:var(--hw);letter-spacing:var(--ht);line-height:1.05;margin:0}}
.wrap{{width:min(1200px,calc(100% - 48px));margin:0 auto}}
.concept{{background:#0b0f12;color:#aab4ba;text-align:center;font-size:12px;padding:8px 14px}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:12px 20px;border-radius:var(--r);font-weight:700;font-size:15px;transition:transform .15s ease,box-shadow .15s ease;white-space:nowrap}}.btn:hover{{transform:translateY(-1px)}}.btn-lg{{padding:16px 26px;font-size:16px}}.btn-accent{{background:var(--accent);color:var(--on-accent);box-shadow:0 10px 24px -12px var(--accent)}}.btn-ghost{{border:1.5px solid currentColor;opacity:.92}}
.site-header{{position:relative;z-index:20;padding:22px 0}}.nav{{display:flex;align-items:center;gap:32px}}.nav-links{{display:flex;gap:28px;margin-left:auto;font-weight:600;font-size:15px}}.nav-links a{{opacity:.85}}.nav-links a:hover{{opacity:1}}.wordmark{{font-family:var(--hf);font-weight:var(--hw);font-size:24px;letter-spacing:var(--ht);line-height:1.1;max-width:340px}}.logo-chip{{display:inline-flex;align-items:center;background:#fff;padding:8px 12px;border-radius:var(--r);box-shadow:0 6px 20px -10px #0006}}.logo-chip.dark{{background:var(--dark)}}.logo-chip img{{height:44px;width:auto;max-width:220px;object-fit:contain}}
.eyebrow,.kicker{{font-size:12px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent-text)}}
h1{{font-size:clamp(42px,6vw,76px);margin:16px 0 20px;max-width:15ch}}.lead{{font-size:19px;line-height:1.65;max-width:56ch;margin:0}}.actions{{display:flex;gap:12px;flex-wrap:wrap;margin-top:32px}}
.proof{{display:inline-flex;align-items:center;gap:12px;background:#fff;color:var(--ink);padding:14px 18px;border-radius:var(--r);box-shadow:0 24px 50px -24px #0007;font-size:14px}}.proof strong{{font-family:var(--hf);font-size:28px;line-height:1}}.proof span{{color:var(--muted)}}.proof-stars,.stars,.proof .proof-stars,.score .stars,.quote .stars{{color:#f5a623;letter-spacing:.06em}}
.hero-bold{{position:relative;min-height:760px;color:#fff;background:radial-gradient(1200px 500px at 85% 10%,color-mix(in srgb,var(--accent) 35%,transparent),transparent 60%),linear-gradient(135deg,var(--dark),var(--ink));overflow:hidden;display:flex;flex-direction:column}}.hero-bold .site-header{{position:absolute;inset:0 0 auto 0}}.hero-bold .eyebrow{{color:var(--accent-dark)}}.hero-bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.hero-bold.has-photo:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,color-mix(in srgb,var(--dark) 92%,transparent) 0%,color-mix(in srgb,var(--dark) 70%,transparent) 42%,transparent 85%),linear-gradient(0deg,color-mix(in srgb,var(--dark) 60%,transparent),transparent 40%)}}.hero-bold .hero-inner{{position:relative;z-index:2;margin-top:auto;padding:170px 0 96px;display:flex;align-items:flex-end;justify-content:space-between;gap:40px}}.hero-bold .lead{{color:#e8edf0}}.hero-bold .btn-ghost{{color:#fff}}
.hero-split{{background:linear-gradient(180deg,#fff,var(--surface))}}.hero-split .hero-inner{{display:grid;grid-template-columns:1.05fr .95fr;gap:64px;align-items:center;padding:40px 0 96px}}.hero-split .lead{{color:var(--muted)}}.hero-visual{{position:relative}}.hero-visual img{{width:100%;aspect-ratio:4/4.4;object-fit:cover;border-radius:var(--rl);box-shadow:0 40px 80px -40px #0005}}.hero-visual .proof{{position:absolute;left:-28px;bottom:32px}}.hero-panel{{aspect-ratio:4/4.4;border-radius:var(--rl);background:linear-gradient(150deg,var(--ink),var(--dark));color:#fff;display:flex;flex-direction:column;justify-content:center;padding:48px;gap:10px}}.hero-panel strong{{font-family:var(--hf);font-size:34px;line-height:1.1}}.hero-panel>span{{color:var(--muted-dark)}}.panel-icon{{width:76px;height:76px;border-radius:var(--r);display:grid;place-items:center;background:var(--accent);color:var(--on-accent);margin-bottom:12px}}
.style-soft .hero-visual img,.style-soft .hero-panel{{border-radius:999px 999px var(--rl) var(--rl)}}.style-soft h1{{font-size:clamp(44px,6.2vw,80px);max-width:14ch}}.style-soft .hero-split{{background:var(--surface)}}
.stats-wrap{{position:relative;z-index:5;margin-top:-44px}}.style-clean .stats-wrap,.style-soft .stats-wrap{{margin-top:-48px}}.stats{{display:grid;grid-template-columns:repeat(var(--n),1fr);background:#fff;border:1px solid var(--line);border-radius:var(--rl);box-shadow:0 30px 60px -36px #0004;overflow:hidden}}.stat{{padding:26px 30px;border-left:1px solid var(--line)}}.stat:first-child{{border-left:0}}.stat strong{{display:block;font-family:var(--hf);font-weight:var(--hw);font-size:30px;letter-spacing:var(--ht);line-height:1.1}}.stat small{{color:#f5a623;font-size:22px;margin-left:4px}}.stat span{{font-size:13px;color:var(--muted)}}
.section{{padding:104px 0}}.section.alt{{background:var(--surface)}}.head{{display:flex;align-items:flex-end;justify-content:space-between;gap:40px;margin-bottom:44px}}.head p{{max-width:420px;color:var(--muted);margin:0}}h2{{font-size:clamp(34px,4.2vw,52px);margin-top:12px;max-width:20ch}}
.grid{{display:grid;grid-template-columns:repeat(var(--cols,3),minmax(0,1fr));gap:20px}}.card{{background:#fff;border:1px solid var(--line);border-radius:var(--rl);padding:30px}}.service{{display:flex;flex-direction:column;transition:transform .2s ease,box-shadow .2s ease}}.service:hover{{transform:translateY(-3px);box-shadow:0 30px 50px -34px #0005}}.icon{{width:52px;height:52px;border-radius:var(--r);display:grid;place-items:center;background:var(--accent-soft);color:var(--accent-text)}}.service h3{{font-size:23px;margin:22px 0 10px}}.service p{{color:var(--muted);font-size:15px;margin:0 0 24px}}.more{{margin-top:auto;font-weight:700;font-size:14px;color:var(--accent-text)}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:72px;align-items:center}}.about-visual img{{width:100%;aspect-ratio:5/4.6;object-fit:cover;border-radius:var(--rl)}}.about-panel{{border-radius:var(--rl);background:linear-gradient(150deg,var(--ink),var(--dark));padding:28px}}.tiles{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.tile{{background:color-mix(in srgb,#fff 6%,transparent);border:1px solid var(--line-dark);border-radius:var(--r);padding:22px;color:#fff;min-height:132px;display:flex;flex-direction:column;justify-content:space-between;gap:16px}}.tile span{{color:var(--accent-dark)}}.tile b{{font-family:var(--hf);font-weight:var(--hw);font-size:17px;line-height:1.25}}.stats-spacer{{height:24px}}.body{{color:var(--muted);font-size:17px;margin:20px 0 0}}.checks{{list-style:none;padding:0;margin:28px 0 34px;display:grid;gap:14px}}.checks li{{display:flex;gap:12px;align-items:flex-start;font-weight:500}}.checks svg{{color:var(--accent-text);flex:none;margin-top:2px}}
.score{{display:flex;align-items:center;gap:14px}}.score strong{{font-family:var(--hf);font-size:60px;line-height:1;font-weight:var(--hw)}}.score span{{color:var(--muted);font-size:14px;display:block}}.score .stars{{font-size:20px}}.reviews{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px}}.reviews.solo{{grid-template-columns:1fr}}.quote-stack{{display:grid;gap:20px}}.quote{{display:flex;flex-direction:column}}.quote p{{flex:1;color:var(--ink);margin:12px 0 20px}}.featured{{background:var(--ink);color:#fff;border:0;padding:44px}}.featured blockquote{{flex:1;margin:18px 0 28px;font-family:var(--hf);font-size:clamp(20px,2vw,26px);line-height:1.35;font-weight:var(--hw);letter-spacing:-.01em}}.quote footer{{display:flex;gap:12px;align-items:center}}.avatar{{position:relative;width:44px;height:44px;border-radius:50%;overflow:hidden;display:grid;place-items:center;background:var(--accent);color:var(--on-accent);font-weight:700;flex:none}}.avatar img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.quote small{{display:block;color:var(--muted);font-size:13px}}.featured small{{color:var(--muted-dark)}}.quote small a{{text-decoration:underline}}.after{{margin:28px 0 0}}.text-link{{font-weight:700;border-bottom:2px solid var(--accent);color:var(--ink)}}.rating-band{{display:grid;grid-template-columns:auto 1fr;gap:56px;align-items:center}}.score.big strong{{font-size:110px}}
.dark{{background:var(--dark);color:#fff}}.style-soft .dark{{background:var(--accent-soft);color:var(--ink)}}.style-soft .dark .kicker,.style-soft .num{{color:var(--accent-text)}}.style-soft .step{{background:#fff;border-color:var(--line)}}.style-soft .step p{{color:var(--muted)}}.dark .kicker{{color:var(--accent-dark)}}.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:44px}}.step{{border:1px solid var(--line-dark);border-radius:var(--rl);padding:30px;background:color-mix(in srgb,#fff 4%,transparent)}}.num{{font-family:var(--hf);font-size:15px;font-weight:700;color:var(--accent-dark)}}.step h3{{font-size:22px;margin:18px 0 10px}}.step p{{margin:0;color:var(--muted-dark);font-size:15px}}
.chips{{list-style:none;padding:0;margin:28px 0 0;display:flex;flex-wrap:wrap;gap:10px}}.chips li{{display:inline-flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);border-radius:999px;padding:10px 16px;font-weight:600;font-size:14px}}.chips svg{{color:var(--accent-text)}}.map{{border-radius:var(--rl);overflow:hidden;border:1px solid var(--line);aspect-ratio:4/3;background:#e9ecee}}.map iframe{{width:100%;height:100%;border:0}}.areas-solo h2{{max-width:22ch}}
.faq-split{{align-items:start;grid-template-columns:.8fr 1.2fr}}.faq details{{border-top:1px solid var(--line);padding:22px 0}}.faq details:last-child{{border-bottom:1px solid var(--line)}}.faq summary{{cursor:pointer;list-style:none;display:flex;justify-content:space-between;gap:24px;font-weight:700;font-size:17px}}.faq summary::-webkit-details-marker{{display:none}}.faq summary:after{{content:"+";color:var(--accent-text);font-size:22px;line-height:1}}.faq details[open] summary:after{{content:"–"}}.faq p{{color:var(--muted);margin:12px 40px 0 0}}
.cta{{background:var(--ink);color:#fff;padding:96px 0}}.cta .kicker{{color:var(--accent-dark)}}.cta-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:64px;align-items:center}}.cta p{{color:var(--muted-dark);font-size:18px;margin:16px 0 0}}.contact-lines{{display:grid;gap:12px;margin:28px 0 32px}}.contact-line{{display:flex;gap:12px;align-items:center;font-size:18px;font-weight:600}}.contact-line svg{{color:var(--accent-dark)}}.hours-card{{background:color-mix(in srgb,#fff 6%,transparent);border:1px solid var(--line-dark);border-radius:var(--rl);padding:30px}}.hours-card h3{{display:flex;gap:10px;align-items:center;font-size:20px;margin-bottom:16px}}.hours-card svg{{color:var(--accent-dark)}}.hours-card ul{{list-style:none;margin:0;padding:0}}.hours-card li{{display:flex;justify-content:space-between;gap:20px;padding:10px 0;border-top:1px solid var(--line-dark);font-size:15px}}.hours-card li span:first-child{{font-weight:600}}.hours-card li span:last-child{{color:var(--muted-dark);text-align:right}}
.hero-form{{width:380px;flex:none;position:relative;z-index:3}}.lead-form{{background:#fff;color:var(--ink);border-radius:var(--rl);padding:28px;box-shadow:0 40px 80px -40px #0008;display:grid;gap:12px}}.lead-form h3{{font-size:22px}}.lead-form .form-sub{{margin:-6px 0 4px;color:var(--muted);font-size:14px}}.cta .lead-form p{{color:var(--muted)}}.lead-form label{{display:grid;gap:6px;font-size:13px;font-weight:600}}.lead-form label span{{font-weight:400;color:var(--muted)}}.lead-form input,.lead-form select,.lead-form textarea{{font:inherit;font-size:15px;font-weight:400;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:11px 13px;width:100%}}.lead-form textarea{{resize:vertical}}.lead-form input:focus,.lead-form select:focus,.lead-form textarea:focus{{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}}.lead-form button{{width:100%;margin-top:4px;border:0;cursor:pointer;font:inherit;font-weight:700}}.lead-form button:disabled{{opacity:.6;cursor:default}}.form-note{{margin:0;font-size:13px;color:var(--muted);background:var(--accent-soft);border-radius:var(--r);padding:10px 12px}}.areas-layout{{display:grid;gap:24px}}.areas-layout.with-map{{grid-template-columns:1fr 1.15fr;align-items:stretch}}.areas-layout.with-map .map{{aspect-ratio:auto;min-height:100%}}.area-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.areas-layout:not(.with-map) .area-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.area-card{{background:#fff;border:1px solid var(--line);border-radius:var(--rl);padding:22px;display:flex;flex-direction:column;gap:10px}}.area-top{{display:flex;gap:10px;align-items:center}}.area-top svg{{color:var(--accent-text);flex:none}}.area-card h3{{font-size:18px;line-height:1.2}}.area-card p{{margin:0;color:var(--muted);font-size:14px;flex:1}}.area-more{{margin:24px 0 0;color:var(--muted)}}.contact-form .lead-form{{box-shadow:0 40px 80px -40px #000a}}.cta .hours-card{{margin-top:28px;max-width:440px}}
.site-footer{{background:var(--dark);color:var(--muted-dark);padding:72px 0 30px;font-size:14px}}.foot{{display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:48px}}.foot-name{{display:block;color:#fff;font-family:var(--hf);font-size:22px;font-weight:var(--hw)}}.foot p{{margin:8px 0 0}}.foot-phone{{display:inline-block;margin-top:16px;color:#fff;font-size:20px;font-weight:700}}.site-footer h4{{margin:0 0 14px;color:#fff;font-size:12px;letter-spacing:.14em;text-transform:uppercase}}.site-footer ul{{list-style:none;margin:0;padding:0;display:grid;gap:8px}}.foot-base{{display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-top:48px;padding-top:24px;border-top:1px solid var(--line-dark);font-size:12px}}
.mobile-call{{display:none;position:fixed;z-index:40;left:12px;right:12px;bottom:12px;background:var(--accent);color:var(--on-accent);padding:15px;border-radius:var(--r);text-align:center;font-weight:700;box-shadow:0 18px 40px #0005}}
@media(max-width:1020px){{.nav-links{{display:none}}.nav-cta{{margin-left:auto}}.hero-split .hero-inner,.split,.cta-grid,.faq-split,.rating-band{{grid-template-columns:1fr;gap:40px}}.hero-visual .proof{{left:16px;bottom:16px}}.reviews{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.steps{{grid-template-columns:1fr}}.hero-bold .hero-inner{{flex-direction:column;align-items:flex-start}}.hero-form{{width:100%;max-width:440px}}.areas-layout.with-map{{grid-template-columns:1fr}}.areas-layout.with-map .map{{aspect-ratio:4/3}}.areas-layout:not(.with-map) .area-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:680px){{.wrap{{width:calc(100% - 32px)}}.wordmark{{font-size:19px;max-width:200px}}.logo-chip img{{height:36px;max-width:160px}}.nav-cta{{display:none}}.hero-bold{{min-height:640px}}.hero-bold .hero-inner{{flex-direction:column;align-items:flex-start;padding:130px 0 80px}}.hero-split .hero-inner{{padding:20px 0 80px}}.lead{{font-size:17px}}.btn-lg{{width:100%}}.stats{{grid-template-columns:1fr 1fr}}.stat{{padding:20px}}.stat:nth-child(3){{border-left:0}}.stat:nth-child(n+3){{border-top:1px solid var(--line)}}.section{{padding:72px 0}}.head{{display:block}}.head p{{margin-top:14px}}.grid{{grid-template-columns:1fr}}.featured{{padding:30px}}.score.big strong{{font-size:80px}}.foot{{grid-template-columns:1fr 1fr}}.foot>div:first-child{{grid-column:1/-1}}.mobile-call{{display:block}}.site-footer{{padding-bottom:100px}}.hero-visual img,.hero-panel{{aspect-ratio:4/3.4}}.about-panel{{display:none}}.hero-form{{display:none}}.area-grid,.areas-layout:not(.with-map) .area-grid{{grid-template-columns:1fr}}.lead-form{{padding:22px}}.style-soft .hero-visual img,.style-soft .hero-panel{{border-radius:var(--rl)}}}}
"""

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex,nofollow,noarchive" />
<meta name="referrer" content="no-referrer" />
<title>{name} | {_safe(category_raw)} in {location or city}</title>
<meta name="description" content="{name}, {category_lower} in {location or city}. {_safe(unit.capitalize())}s, areas served, reviews and how to get in touch." />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{spec['font_query']}&amp;display=swap" />
<script type="application/ld+json">{_schema_json(source, services, areas, address_raw or None)}</script>
<style>{css}</style>
</head>
<body class="style-{style}">
<div class="concept">Concept website prepared by Lilos Growth for demonstration purposes. Not affiliated with or endorsed by {name}.</div>
{hero}
{stats_strip}
<main>
{services_section}
{about_section}
{reviews_section}
{process_section}
{areas_section}
{faq_section}
{contact_section}
</main>
{footer}
{mobile_call}
<script>document.querySelectorAll("form.lead-form").forEach(function(f){{f.addEventListener("submit",function(e){{e.preventDefault();f.querySelector(".form-note").hidden=false;f.querySelector("button").disabled=true;}});}});</script>
</body>
</html>'''
