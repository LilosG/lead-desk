from __future__ import annotations

import json
from html import escape
from typing import Any


V3_TEMPLATE_OPTION = {
    "key": "trade-modern-v3",
    "name": "Trade Modern v3",
    "description": (
        "Full local home-service homepage with conversion-focused hero, services, local trust, "
        "process, reputation, service areas, FAQ, and final contact CTA."
    ),
}


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
    if source.get("rating") is not None and source.get("review_count") is not None:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": float(source["rating"]),
            "reviewCount": int(source["review_count"]),
        }
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
    category_raw = str(source.get("primary_type_display") or "Home Service Professional")
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
    call_label = f"Call {phone}" if phone else "Request service"

    reputation_text = ""
    if rating is not None and review_count is not None:
        reputation_text = f"{float(rating):.1f} Google rating · {int(review_count):,} reviews"
    elif review_count is not None:
        reputation_text = f"{int(review_count):,} Google reviews"

    hero_photo = (
        f'<img class="hero-photo" src="{hero_image}" alt="{business_name} {category_lower} service concept" loading="eager" />'
        if hero_image else ""
    )
    hero_class = "hero has-photo" if hero_image else "hero"

    proof_card = ""
    if reputation_text:
        proof_card = (
            '<div class="proof-card"><div class="stars">★★★★★</div>'
            f'<strong>{_safe(reputation_text)}</strong><span>Public Google reputation</span></div>'
        )

    service_cards = "".join(
        f'''<article class="service-card">
          <div class="service-icon">{index:02d}</div>
          <h3>{_safe(service)}</h3>
          <p>Talk directly with {business_name} to confirm scope, availability, and project details.</p>
          <a href="{call_href}">Ask about this service <span>→</span></a>
        </article>'''
        for index, service in enumerate(services[:6], start=1)
    )

    area_chips = "".join(f"<li>{_safe(area)}</li>" for area in service_areas[:8])
    service_names = ", ".join(_safe(item) for item in services[:4])
    area_names = ", ".join(_safe(item) for item in service_areas[:5])

    media = ""
    if work_image:
        media = f'<img class="about-photo" src="{work_image}" alt="{business_name} service work concept" loading="lazy" />'
    elif secondary_image:
        media = f'<img class="about-photo" src="{secondary_image}" alt="{business_name} local service concept" loading="lazy" />'

    gallery = ""
    if work_image and secondary_image:
        gallery = f'''<section class="gallery-band" aria-label="Service imagery">
          <div class="wrap gallery-grid">
            <img src="{work_image}" alt="{business_name} service work concept" loading="lazy" />
            <img src="{secondary_image}" alt="{business_name} additional service concept" loading="lazy" />
          </div>
        </section>'''

    rating_stat = (
        f'<strong>{float(rating):.1f}</strong><span>Google rating</span>'
        if rating is not None
        else f'<strong>{len(services[:6])}</strong><span>Services highlighted</span>'
    )
    review_stat = (
        f'<strong>{int(review_count):,}</strong><span>Google reviews</span>'
        if review_count is not None
        else f'<strong>{len(service_areas[:8])}</strong><span>Areas shown</span>'
    )

    reputation_section = ""
    if reputation_text:
        reputation_section = f'''<section class="reputation">
          <div class="wrap reputation-grid">
            <div>
              <div class="section-kicker">Local reputation</div>
              <h2>Public reputation customers can see before they call.</h2>
              <p>Google currently shows <strong>{business_name}</strong> at <strong>{float(rating):.1f} stars</strong> across <strong>{int(review_count):,} reviews</strong>. This concept keeps that proof visible near the decision point without inventing testimonial copy.</p>
            </div>
            <div class="rating-panel"><div class="big-rating">{float(rating):.1f}</div><div class="stars">★★★★★</div><strong>{int(review_count):,} Google reviews</strong><span>Public aggregate reputation data</span></div>
          </div>
        </section>'''

    faq_items = [
        (
            f"What areas does {business_name} serve?",
            f"The service areas currently confirmed for this concept include {area_names}. Call to confirm availability for your exact address.",
        ),
        (
            f"What services does {business_name} offer?",
            f"The services highlighted here include {service_names}. Call to confirm the exact scope for your project.",
        ),
        (
            "How do I request service?",
            f"Call {phone or business_name} directly to discuss the work, confirm availability, and determine the next step.",
        ),
        (
            "Can I ask about a service that is not listed here?",
            "Yes. The homepage highlights the services confirmed for this concept; call the business directly to verify other work or special requests.",
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
  <meta name="description" content="{business_name} {category_lower} services in {location}. View services, service areas, public reputation, FAQs, and direct contact information." />
  <title>{business_name} | {category} in {location}</title>
  <script type="application/ld+json">{schema_json}</script>
  <style>
    :root{{--ink:{palette['ink']};--accent:{palette['accent']};--surface:{palette['surface']};--paper:#fff;--muted:#647078;--line:#dfe4e7;--dark:#0b1720}}
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff;line-height:1.55}}a{{color:inherit;text-decoration:none}}img{{display:block;max-width:100%}}.wrap{{width:min(1180px,calc(100% - 40px));margin:0 auto}}
    .concept{{background:#08121a;color:#bac5ca;text-align:center;font-size:11px;padding:7px 14px}}
    header{{position:absolute;z-index:10;left:0;right:0;color:#fff;padding:24px 0}}.nav{{display:flex;align-items:center;justify-content:space-between;gap:24px}}.brand{{font-size:21px;font-weight:850;letter-spacing:-.035em}}.nav-links{{display:flex;align-items:center;gap:24px;font-size:13px}}.nav-links a{{opacity:.85}}.nav-call{{border:1px solid #ffffff42;padding:9px 13px;border-radius:8px;font-weight:800;background:#ffffff0d;opacity:1!important}}
    .hero{{position:relative;min-height:720px;overflow:hidden;background:linear-gradient(120deg,var(--ink) 0%,#1b3346 72%,#3e4c55 100%);color:#fff;display:grid;align-items:end;padding:158px 0 80px}}.hero-photo{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.hero.has-photo:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,17,28,.97),rgba(8,25,39,.86) 45%,rgba(8,25,39,.28) 82%)}}.hero:not(.has-photo):after{{content:"";position:absolute;inset:0;background:radial-gradient(circle at 82% 24%,color-mix(in srgb,var(--accent) 32%,transparent),transparent 25%)}}.hero-grid{{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.55fr);gap:58px;align-items:end}}.eyebrow,.section-kicker{{font-size:11px;font-weight:850;letter-spacing:.17em;text-transform:uppercase;color:var(--accent)}}h1{{font-size:clamp(48px,6.5vw,82px);line-height:.98;letter-spacing:-.055em;margin:15px 0 22px;max-width:850px}}.hero-copy{{font-size:18px;line-height:1.7;color:#e4eaee;max-width:680px;margin:0}}.actions{{display:flex;gap:11px;flex-wrap:wrap;margin-top:29px}}.button{{display:inline-flex;align-items:center;justify-content:center;padding:13px 18px;border-radius:8px;font-weight:850;font-size:14px}}.button-primary{{background:var(--accent);color:#101820}}.button-secondary{{border:1px solid #ffffff55;background:#ffffff0c}}.proof-card{{border:1px solid #ffffff2d;background:#ffffff12;backdrop-filter:blur(12px);padding:23px;border-radius:14px}}.stars{{color:var(--accent);letter-spacing:.08em}}.proof-card strong{{display:block;font-size:20px;margin-top:8px}}.proof-card span{{display:block;color:#cbd4d9;font-size:12px;margin-top:4px}}
    .trust-bar{{position:relative;z-index:4;margin-top:-28px}}.trust-grid{{display:grid;grid-template-columns:1.25fr .75fr .75fr .85fr;background:#fff;border:1px solid var(--line);box-shadow:0 18px 45px #10203012}}.trust-cell{{padding:22px 25px;border-left:1px solid var(--line)}}.trust-cell:first-child{{border-left:0}}.trust-cell strong{{display:block;font-size:18px;letter-spacing:-.02em}}.trust-cell span{{font-size:12px;color:var(--muted)}}
    section{{padding:82px 0}}.section-head{{display:flex;align-items:end;justify-content:space-between;gap:36px;margin-bottom:34px}}.section-head h2,.about-copy h2,.why h2,.process h2,.reputation h2,.areas h2,.faq h2,.contact h2{{font-size:clamp(36px,4.3vw,54px);line-height:1.02;letter-spacing:-.047em;margin:8px 0 0}}.section-head p{{max-width:480px;margin:0;color:var(--muted)}}
    .services{{background:var(--surface)}}.service-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.service-card{{background:#fff;border:1px solid var(--line);padding:25px;min-height:225px;display:flex;flex-direction:column}}.service-icon{{font-size:11px;font-weight:850;color:#9a6c13}}.service-card h3{{font-size:22px;line-height:1.15;letter-spacing:-.035em;margin:24px 0 10px}}.service-card p{{font-size:13px;color:var(--muted);margin:0 0 25px}}.service-card a{{margin-top:auto;font-size:12px;font-weight:850;color:#4d5a62}}.service-card a span{{color:#9a6c13}}
    .about-grid{{display:grid;grid-template-columns:{'1fr 1fr' if media else '1fr'};gap:58px;align-items:center}}.about-photo{{width:100%;height:500px;object-fit:cover;border-radius:16px;box-shadow:0 20px 50px #10203018}}.about-copy p{{font-size:16px;color:var(--muted);max-width:650px}}.about-points{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:28px}}.about-point{{border:1px solid var(--line);padding:18px;border-radius:10px}}.about-point strong{{display:block;font-size:14px}}.about-point span{{display:block;color:var(--muted);font-size:12px;margin-top:5px}}
    .why{{background:var(--dark);color:#fff}}.why h2{{max-width:720px}}.why-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:36px}}.why-card{{border:1px solid #ffffff22;background:#ffffff08;padding:26px;border-radius:12px}}.why-card b{{display:grid;place-items:center;width:34px;height:34px;border-radius:999px;background:var(--accent);color:#111}}.why-card h3{{font-size:20px;margin:22px 0 9px}}.why-card p{{color:#bcc7cd;font-size:13px;margin:0}}
    .process-grid{{display:grid;grid-template-columns:.8fr 1.2fr;gap:60px;align-items:start}}.steps{{display:grid;gap:0;border-top:1px solid var(--line)}}.step{{display:grid;grid-template-columns:56px 1fr;gap:18px;padding:24px 0;border-bottom:1px solid var(--line)}}.step-number{{font-weight:850;color:#9a6c13}}.step h3{{margin:0 0 6px;font-size:20px}}.step p{{margin:0;color:var(--muted);font-size:13px}}
    .reputation{{background:var(--surface)}}.reputation-grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:58px;align-items:center}}.reputation p{{font-size:16px;color:var(--muted);max-width:700px}}.rating-panel{{background:#fff;border:1px solid var(--line);padding:34px;border-radius:14px;text-align:center;box-shadow:0 18px 45px #1020300d}}.big-rating{{font-size:72px;line-height:1;font-weight:900;letter-spacing:-.06em}}.rating-panel strong,.rating-panel span{{display:block}}.rating-panel strong{{margin-top:12px}}.rating-panel span{{font-size:12px;color:var(--muted);margin-top:5px}}
    .gallery-band{{padding:0 0 82px}}.gallery-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.gallery-grid img{{width:100%;height:360px;object-fit:cover;border-radius:14px}}
    .areas{{background:#0d1a24;color:#fff}}.areas-grid{{display:grid;grid-template-columns:.82fr 1.18fr;gap:60px;align-items:center}}.areas p{{color:#bdc7cc}}.areas ul{{display:flex;flex-wrap:wrap;gap:10px;list-style:none;padding:0;margin:0}}.areas li{{border:1px solid #ffffff24;background:#ffffff0b;padding:10px 14px;border-radius:999px;font-size:13px}}
    .faq-grid{{display:grid;grid-template-columns:.72fr 1.28fr;gap:60px;align-items:start}}.faq p{{color:var(--muted)}}details{{border-top:1px solid var(--line);padding:18px 0}}details:last-child{{border-bottom:1px solid var(--line)}}summary{{cursor:pointer;font-weight:800;font-size:16px;list-style:none;display:flex;justify-content:space-between;gap:20px}}summary:after{{content:"+";color:#9a6c13}}details[open] summary:after{{content:"–"}}details p{{margin:10px 36px 0 0!important;font-size:13px}}
    .contact{{background:var(--accent);padding:68px 0}}.contact-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:60px;align-items:center}}.contact h2{{max-width:760px}}.contact p{{max-width:650px;margin:14px 0 0;color:#27323a}}.contact-card{{background:#0d1a24;color:#fff;padding:28px;border-radius:14px}}.contact-card span{{display:block;color:#b9c4ca;font-size:12px}}.contact-card strong{{display:block;font-size:25px;margin:6px 0 18px}}.contact-card .button{{width:100%;background:#fff;color:#0d1a24}}
    footer{{padding:30px 0;color:var(--muted);font-size:12px}}.footer-grid{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}.mobile-call{{display:none;position:fixed;z-index:30;left:12px;right:12px;bottom:12px;background:var(--accent);color:#111820;padding:14px;border-radius:10px;text-align:center;font-weight:850;box-shadow:0 18px 45px #0005}}
    @media(max-width:840px){{.wrap{{width:min(100% - 28px,1180px)}}.nav-links a:not(.nav-call){{display:none}}.hero{{min-height:650px;padding:125px 0 58px}}.hero-grid,.about-grid,.process-grid,.reputation-grid,.areas-grid,.faq-grid,.contact-grid{{grid-template-columns:1fr;gap:32px}}.hero-grid{{gap:28px}}.proof-card{{max-width:360px}}.trust-grid{{grid-template-columns:1fr 1fr}}.trust-cell:nth-child(3){{border-left:0;border-top:1px solid var(--line)}}.trust-cell:nth-child(4){{border-top:1px solid var(--line)}}section{{padding:64px 0}}.section-head{{display:block}}.section-head p{{margin-top:16px}}.service-grid,.why-grid{{grid-template-columns:1fr}}.about-points{{grid-template-columns:1fr}}.about-photo{{height:360px}}.gallery-grid{{grid-template-columns:1fr}}.gallery-grid img{{height:300px}}.mobile-call{{display:block}}body{{padding-bottom:72px}}}}
  </style>
</head>
<body>
  <div class="concept">Concept website prepared by LILOs Growth for demonstration purposes. Not affiliated with or endorsed by {business_name}.</div>
  <header><div class="wrap nav"><div class="brand">{business_name}</div><nav class="nav-links"><a href="#services">Services</a><a href="#about">About</a><a href="#areas">Service area</a><a href="#faq">FAQ</a><a class="nav-call" href="{call_href}">{call_label}</a></nav></div></header>
  <main>
    <section class="{hero_class}">{hero_photo}<div class="wrap hero-grid"><div><div class="eyebrow">{category} · {location}</div><h1>{headline}</h1><p class="hero-copy">{subheadline}</p><div class="actions"><a class="button button-primary" href="{call_href}">{call_label}</a><a class="button button-secondary" href="#services">View services</a></div></div>{proof_card}</div></section>
    <div class="trust-bar"><div class="wrap trust-grid"><div class="trust-cell"><strong>{business_name}</strong><span>{category} serving {area_names}</span></div><div class="trust-cell">{rating_stat}</div><div class="trust-cell">{review_stat}</div><div class="trust-cell"><strong>{len(service_areas[:8])}</strong><span>Service areas highlighted</span></div></div></div>
    <section id="services" class="services"><div class="wrap"><div class="section-head"><div><div class="section-kicker">Services</div><h2>{category} services for {city}</h2></div><p>Clear service coverage gives customers a faster path from search to the work they need. Call directly to confirm availability and scope.</p></div><div class="service-grid">{service_cards}</div></div></section>
    <section id="about"><div class="wrap about-grid">{media}<div class="about-copy"><div class="section-kicker">Local service</div><h2>A clearer local presence for customers who are ready to hire.</h2><p>{business_name} is presented here around the facts customers typically look for first: what the business does, where it works, how its public reputation looks, and how to make direct contact.</p><div class="about-points"><div class="about-point"><strong>Local relevance</strong><span>{location} and confirmed nearby service areas are prominent throughout the page.</span></div><div class="about-point"><strong>Service clarity</strong><span>{len(services[:6])} confirmed service categories are easy to scan and act on.</span></div><div class="about-point"><strong>Reputation proof</strong><span>{_safe(reputation_text or 'Public reputation can be added when verified.')}</span></div><div class="about-point"><strong>Direct contact</strong><span>{'Phone contact is visible throughout the page.' if phone else 'A contact path can be added when confirmed.'}</span></div></div></div></div></section>
    <section class="why"><div class="wrap"><div class="section-kicker">Why this experience works</div><h2>Built around the questions local service customers ask before they call.</h2><div class="why-grid"><article class="why-card"><b>1</b><h3>Can you do the work?</h3><p>Service categories are visible early, with direct paths to ask about scope and availability.</p></article><article class="why-card"><b>2</b><h3>Do you serve my area?</h3><p>Confirmed cities and service areas are reinforced across the page instead of hidden in the footer.</p></article><article class="why-card"><b>3</b><h3>How do I contact you?</h3><p>The primary call action stays visible from the hero through the final conversion section.</p></article></div></div></section>
    <section class="process"><div class="wrap process-grid"><div><div class="section-kicker">Simple next steps</div><h2>From search to service request.</h2></div><div class="steps"><div class="step"><div class="step-number">01</div><div><h3>Choose the service you need</h3><p>Start with the service categories shown above or call to discuss a project that is not listed.</p></div></div><div class="step"><div class="step-number">02</div><div><h3>Confirm the details</h3><p>Use direct phone contact to confirm the address, scope, timing, and availability.</p></div></div><div class="step"><div class="step-number">03</div><div><h3>Determine the next step</h3><p>The business can then confirm scheduling, an estimate, or any additional information needed.</p></div></div></div></div></section>
    {reputation_section}
    {gallery}
    <section id="areas" class="areas"><div class="wrap areas-grid"><div><div class="section-kicker">Service area</div><h2>Serving {city} and nearby communities.</h2><p>These are the service areas currently confirmed for this concept. Call to verify availability for your exact property.</p></div><ul>{area_chips}</ul></div></section>
    <section id="faq" class="faq"><div class="wrap faq-grid"><div><div class="section-kicker">Frequently asked questions</div><h2>Quick answers before you call.</h2><p>Useful local-service FAQs help customers understand coverage and next steps without making unverified claims.</p></div><div>{faq_markup}</div></div></section>
    <section id="contact" class="contact"><div class="wrap contact-grid"><div><div class="section-kicker" style="color:#26313a">Contact</div><h2>Need {category_lower} service in {city}?</h2><p>Call {business_name} directly to discuss your project, confirm service availability, and determine the next step.</p></div><div class="contact-card"><span>Direct contact</span><strong>{phone or business_name}</strong><a class="button" href="{call_href}">{call_label}</a></div></div></section>
  </main>
  <footer><div class="wrap footer-grid"><strong>{business_name}</strong><span>{phone} · {location}</span><span>Concept website by LILOs Growth</span></div></footer>
  {f'<a class="mobile-call" href="{call_href}">{call_label}</a>' if phone else ''}
</body>
</html>'''
