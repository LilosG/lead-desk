from html import escape
from typing import Any


TEMPLATES = {
    "trade-modern-v2": {
        "name": "Trade Modern v2",
        "description": "Photo-forward local-service homepage with tighter spacing, individual service cards, reputation proof, and a stronger sales presentation.",
    },
    "trade-modern-v1": {
        "name": "Trade Modern v1",
        "description": "Original high-trust home-service concept retained for existing demo continuity.",
    },
}


PALETTES = {
    "electrician": {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"},
    "plumber": {"ink": "#0e2c43", "accent": "#2f91c3", "surface": "#f1f7fa"},
    "hvac": {"ink": "#17303b", "accent": "#df7840", "surface": "#f5f6f4"},
    "roofer": {"ink": "#272b2e", "accent": "#ba6847", "surface": "#f5f3f0"},
    "default": {"ink": "#18272f", "accent": "#b88747", "surface": "#f5f4f1"},
}


def template_options() -> list[dict[str, str]]:
    return [
        {"key": key, "name": value["name"], "description": value["description"]}
        for key, value in TEMPLATES.items()
    ]


def palette_for(primary_type: str | None) -> dict[str, str]:
    key = (primary_type or "").lower().replace(" ", "_")
    return dict(PALETTES.get(key, PALETTES["default"]))


def _safe(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _phone_href(phone: str | None) -> str:
    if not phone:
        return "#contact"
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return f"tel:{digits}" if digits else "#contact"


def _stars(rating: object) -> str:
    """Stars that match the real rating, never a flat five."""
    if rating is None:
        return ""
    full = max(0, min(5, int(round(float(rating)))))
    return "★" * full + "☆" * (5 - full)


def _reputation_text(rating: object, review_count: object) -> str:
    if rating is not None and review_count is not None:
        return f"{float(rating):.1f} Google rating · {int(review_count):,} reviews"
    if review_count is not None:
        return f"{int(review_count):,} Google reviews"
    return ""


def _render_v2(*, source: dict[str, Any], content: dict[str, Any], brand: dict[str, Any]) -> str:
    business_name = _safe(source.get("name"))
    city = _safe(source.get("city"))
    state = _safe(source.get("state"))
    location = ", ".join(part for part in [city, state] if part)
    phone = _safe(source.get("phone"))
    category = _safe(source.get("primary_type_display") or "Local Business")
    category_lower = _safe((source.get("primary_type_display") or "home service").lower())
    rating = source.get("rating")
    review_count = source.get("review_count")
    services = [str(item).strip() for item in content.get("services", []) if str(item).strip()]
    service_areas = [str(item).strip() for item in content.get("service_areas", []) if str(item).strip()]
    headline = _safe(content.get("headline"))
    subheadline = _safe(content.get("subheadline"))
    hero_image = _safe(content.get("hero_image_url"))
    work_image = _safe(content.get("work_image_url"))
    secondary_image = _safe(content.get("secondary_image_url"))
    palette = brand.get("palette") or PALETTES["default"]

    if not services:
        services = [str(source.get("primary_type_display") or "Local Business")]
    if not service_areas and city:
        service_areas = [str(source.get("city"))]

    reputation = _reputation_text(rating, review_count)
    call_href = _safe(_phone_href(source.get("phone")))
    call_label = f"Call {phone}" if phone else "Request service"
    area_text = ", ".join(_safe(area) for area in service_areas[:3])

    hero_photo = (
        f'<img class="hero-photo" src="{hero_image}" alt="{business_name} {category_lower} service concept" loading="eager" />'
        if hero_image else ""
    )
    hero_class = "hero has-photo" if hero_image else "hero"

    reputation_badge = (
        f'<div class="proof-card"><div class="stars">{_stars(rating)}</div><strong>{_safe(reputation)}</strong><span>Public Google reputation</span></div>'
        if reputation else ""
    )

    service_cards = "".join(
        f'''<article class="service-card">
          <div class="service-number">{index:02d}</div>
          <h3>{_safe(service)}</h3>
          <a href="{call_href}">Ask about this service <span>→</span></a>
        </article>'''
        for index, service in enumerate(services[:6], start=1)
    )

    areas = "".join(f"<li>{_safe(area)}</li>" for area in service_areas[:8])

    media_panel = ""
    if work_image:
        media_panel = f'''<div class="work-photo-wrap"><img class="work-photo" src="{work_image}" alt="{business_name} service work concept" loading="lazy" /></div>'''
    elif secondary_image:
        media_panel = f'''<div class="work-photo-wrap"><img class="work-photo" src="{secondary_image}" alt="{business_name} local service concept" loading="lazy" /></div>'''

    secondary_strip = ""
    if work_image and secondary_image:
        secondary_strip = f'''<section class="photo-strip"><img src="{secondary_image}" alt="{business_name} additional service concept" loading="lazy" /></section>'''

    proof_stat = (
        f'<div class="trust-stat"><strong>{float(rating):.1f}</strong><span>Google rating</span></div>'
        if rating is not None else f'<div class="trust-stat"><strong>{len(services[:6])}</strong><span>Core services shown</span></div>'
    )
    reviews_stat = (
        f'<div class="trust-stat"><strong>{int(review_count):,}</strong><span>Google reviews</span></div>'
        if review_count is not None else f'<div class="trust-stat"><strong>{len(service_areas[:8])}</strong><span>Service areas shown</span></div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow,noarchive" />
  <meta name="referrer" content="no-referrer" />
  <title>{business_name} | {category} in {location}</title>
  <style>
    :root{{--ink:{palette['ink']};--accent:{palette['accent']};--surface:{palette['surface']};--paper:#fff;--muted:#647078;--line:#dfe4e7;--dark:#0c1720}}
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--paper);line-height:1.5}}a{{color:inherit;text-decoration:none}}img{{display:block;max-width:100%}}.wrap{{width:min(1180px,calc(100% - 40px));margin:0 auto}}
    .concept{{background:#09131b;color:#b9c3c9;text-align:center;font-size:11px;padding:7px 14px}}
    header{{position:absolute;z-index:10;left:0;right:0;color:#fff;padding:24px 0}}.nav{{display:flex;align-items:center;justify-content:space-between;gap:20px}}.brand{{font-size:21px;font-weight:850;letter-spacing:-.035em}}.nav-right{{display:flex;align-items:center;gap:22px;font-size:13px}}.nav-call{{border:1px solid #ffffff42;padding:9px 13px;border-radius:8px;font-weight:750;background:#ffffff0d}}
    .hero{{position:relative;min-height:690px;overflow:hidden;background:linear-gradient(120deg,var(--ink) 0%,#1c3347 72%,#354959 100%);color:#fff;display:grid;align-items:end;padding:150px 0 72px}}.hero-photo{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.hero.has-photo:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,17,28,.96) 0%,rgba(9,25,39,.87) 43%,rgba(9,25,39,.38) 74%,rgba(9,25,39,.18) 100%)}}.hero:not(.has-photo):after{{content:"";position:absolute;inset:0;background:radial-gradient(circle at 82% 24%,color-mix(in srgb,var(--accent) 34%,transparent),transparent 26%),linear-gradient(120deg,rgba(255,255,255,.02),transparent 55%)}}
    .hero-inner{{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.55fr);gap:54px;align-items:end}}.eyebrow{{font-size:12px;font-weight:850;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}}h1{{font-size:clamp(46px,6.4vw,78px);line-height:.98;letter-spacing:-.055em;margin:15px 0 20px;max-width:800px}}.hero-copy{{font-size:18px;line-height:1.65;color:#e4eaee;max-width:680px;margin:0}}.actions{{display:flex;gap:11px;flex-wrap:wrap;margin-top:28px}}.button{{display:inline-flex;align-items:center;justify-content:center;padding:13px 18px;border-radius:8px;font-weight:800;font-size:14px}}.button-primary{{background:var(--accent);color:#111820}}.button-secondary{{border:1px solid #ffffff55;background:#ffffff0c}}
    .proof-card{{border:1px solid #ffffff2b;background:#ffffff12;backdrop-filter:blur(12px);padding:22px;border-radius:14px;box-shadow:0 24px 60px #0002}}.proof-card .stars{{color:var(--accent);letter-spacing:.08em;font-size:14px;margin-bottom:10px}}.proof-card strong{{display:block;font-size:20px;letter-spacing:-.02em}}.proof-card span{{display:block;margin-top:4px;color:#cbd4d9;font-size:12px}}
    .trust-bar{{position:relative;z-index:4;margin-top:-26px}}.trust-grid{{display:grid;grid-template-columns:1.25fr .75fr .75fr;background:#fff;border:1px solid var(--line);box-shadow:0 18px 45px #10203012}}.trust-intro,.trust-stat{{padding:22px 26px}}.trust-stat{{border-left:1px solid var(--line)}}.trust-intro strong{{display:block;font-size:16px}}.trust-intro span,.trust-stat span{{font-size:12px;color:var(--muted)}}.trust-stat strong{{display:block;font-size:25px;line-height:1.1;letter-spacing:-.03em}}
    section{{padding:74px 0}}.section-kicker{{font-size:11px;font-weight:850;letter-spacing:.16em;text-transform:uppercase;color:#9a6c13}}.section-head{{display:flex;align-items:end;justify-content:space-between;gap:34px;margin-bottom:30px}}.section-head h2{{font-size:clamp(34px,4.2vw,53px);line-height:1.02;letter-spacing:-.045em;margin:7px 0 0;max-width:650px}}.section-head p{{max-width:470px;margin:0;color:var(--muted);font-size:15px}}
    .services{{background:var(--surface)}}.service-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.service-card{{background:#fff;border:1px solid var(--line);padding:24px;min-height:180px;display:flex;flex-direction:column;transition:transform .18s ease,box-shadow .18s ease}}.service-card:hover{{transform:translateY(-3px);box-shadow:0 16px 35px #10203010}}.service-number{{font-size:11px;font-weight:850;color:#a57922}}.service-card h3{{font-size:22px;line-height:1.12;letter-spacing:-.035em;margin:25px 0 28px}}.service-card a{{margin-top:auto;font-size:12px;font-weight:800;color:#52616a}}.service-card a span{{color:#9a6c13;margin-left:4px}}
    .local-proof-grid{{display:grid;grid-template-columns:{'1.05fr .95fr' if media_panel else '1fr'};gap:54px;align-items:center}}.work-photo-wrap{{border-radius:16px;overflow:hidden;min-height:430px;background:#e8ecee;box-shadow:0 20px 50px #10203016}}.work-photo{{width:100%;height:100%;min-height:430px;object-fit:cover}}.local-copy h2{{font-size:clamp(36px,4vw,52px);line-height:1.03;letter-spacing:-.045em;margin:8px 0 18px}}.local-copy p{{font-size:16px;color:var(--muted);margin:0 0 24px;max-width:590px}}.reasons{{display:grid;gap:12px}}.reason{{display:flex;gap:11px;align-items:flex-start;font-size:14px}}.reason b{{display:grid;place-items:center;flex:0 0 24px;height:24px;border-radius:999px;background:var(--surface);color:#9a6c13}}
    .areas{{background:var(--dark);color:#fff}}.areas-grid{{display:grid;grid-template-columns:.8fr 1.2fr;gap:60px;align-items:center}}.areas h2{{font-size:clamp(36px,4vw,50px);line-height:1.04;letter-spacing:-.045em;margin:8px 0 13px}}.areas p{{color:#bac5cb;margin:0}}.areas ul{{display:flex;flex-wrap:wrap;gap:10px;list-style:none;padding:0;margin:0}}.areas li{{border:1px solid #ffffff24;background:#ffffff0b;padding:10px 14px;border-radius:999px;font-size:13px}}
    .photo-strip{{padding:0;height:330px;overflow:hidden}}.photo-strip img{{width:100%;height:100%;object-fit:cover}}
    .cta{{background:var(--accent);padding:58px 0}}.cta-grid{{display:flex;justify-content:space-between;align-items:center;gap:30px}}.cta h2{{font-size:clamp(34px,4vw,48px);line-height:1;letter-spacing:-.045em;margin:5px 0 0;max-width:760px}}.cta .button{{background:#0d1a24;color:#fff}}
    footer{{padding:28px 0;color:var(--muted);font-size:12px}}.footer-grid{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}.mobile-call{{display:none;position:fixed;z-index:30;left:12px;right:12px;bottom:12px;background:var(--accent);color:#111820;padding:14px;border-radius:10px;text-align:center;font-weight:850;box-shadow:0 18px 45px #0005}}
    @media(max-width:820px){{.wrap{{width:min(100% - 28px,1180px)}}header{{padding-top:19px}}.nav-right span{{display:none}}.hero{{min-height:650px;padding:125px 0 55px}}.hero.has-photo:after{{background:linear-gradient(180deg,rgba(6,18,30,.68),rgba(6,18,30,.92) 66%,rgba(6,18,30,.97))}}.hero-inner{{grid-template-columns:1fr;gap:24px}}h1{{font-size:48px}}.proof-card{{max-width:390px}}.trust-grid{{grid-template-columns:1fr 1fr}}.trust-intro{{grid-column:1/-1}}.trust-stat{{border-top:1px solid var(--line)}}.trust-stat:nth-child(2){{border-left:0}}section{{padding:58px 0}}.section-head{{align-items:flex-start;flex-direction:column;gap:15px}}.service-grid{{grid-template-columns:1fr}}.service-card{{min-height:auto}}.local-proof-grid,.areas-grid{{grid-template-columns:1fr;gap:30px}}.work-photo-wrap,.work-photo{{min-height:310px}}.cta-grid{{align-items:flex-start;flex-direction:column}}.mobile-call{{display:block}}body{{padding-bottom:72px}}}}
  </style>
</head>
<body>
  <div class="concept">Concept website prepared by LILOs Growth for demonstration purposes. Not affiliated with or endorsed by {business_name}.</div>
  <header><div class="wrap nav"><div class="brand">{business_name}</div><div class="nav-right"><span>{location}</span><a class="nav-call" href="{call_href}">{call_label}</a></div></div></header>
  <main>
    <section class="{hero_class}">{hero_photo}<div class="wrap hero-inner"><div><div class="eyebrow">{category} · {location}</div><h1>{headline}</h1><p class="hero-copy">{subheadline}</p><div class="actions"><a class="button button-primary" href="{call_href}">{call_label}</a><a class="button button-secondary" href="#services">View services</a></div></div>{reputation_badge}</div></section>
    <div class="trust-bar"><div class="wrap trust-grid"><div class="trust-intro"><strong>{business_name}</strong><span>{category} serving {area_text or location}</span></div>{proof_stat}{reviews_stat}</div></div>
    <section id="services" class="services"><div class="wrap"><div class="section-head"><div><div class="section-kicker">Services</div><h2>{category} services for {city or 'the local area'}</h2></div><p>Explore the core services shown for {business_name}, then call directly to confirm availability and project details.</p></div><div class="service-grid">{service_cards}</div></div></section>
    <section><div class="wrap local-proof-grid">{media_panel}<div class="local-copy"><div class="section-kicker">Local service</div><h2>Help for properties across {city or 'the area'}.</h2><p>{business_name} serves customers in {area_text or location}. Use the direct contact options on this page to ask about service availability, scheduling, and project scope.</p><div class="reasons"><div class="reason"><b>✓</b><span>Core services presented clearly in one place</span></div>{f'<div class="reason"><b>✓</b><span>{_safe(reputation)} from public Google data</span></div>' if reputation else ''}<div class="reason"><b>✓</b><span>Direct phone contact for service questions</span></div></div></div></div></section>
    <section class="areas"><div class="wrap areas-grid"><div><div class="section-kicker" style="color:var(--accent)">Service area</div><h2>Serving {city or 'local communities'} and nearby areas.</h2><p>Call to confirm availability for your address and project.</p></div><ul>{areas}</ul></div></section>
    {secondary_strip}
    <section id="contact" class="cta"><div class="wrap cta-grid"><div><div class="section-kicker" style="color:#28313a">Contact</div><h2>Need {category_lower} service in {city or 'your area'}?</h2></div><a class="button" href="{call_href}">{call_label}</a></div></section>
  </main>
  <footer><div class="wrap footer-grid"><strong>{business_name}</strong><span>{phone}{' · ' if phone and location else ''}{location}</span><span>Concept website by LILOs Growth</span></div></footer>
  {f'<a class="mobile-call" href="{call_href}">{call_label}</a>' if phone else ''}
</body>
</html>"""


def _render_v1(*, source: dict[str, Any], content: dict[str, Any], brand: dict[str, Any]) -> str:
    business_name = _safe(source.get("name"))
    city = _safe(source.get("city"))
    state = _safe(source.get("state"))
    location = ", ".join(part for part in [city, state] if part)
    phone = _safe(source.get("phone"))
    category = _safe(source.get("primary_type_display") or "Local Business")
    rating = source.get("rating")
    review_count = source.get("review_count")
    services = [str(item).strip() for item in content.get("services", []) if str(item).strip()]
    service_areas = [str(item).strip() for item in content.get("service_areas", []) if str(item).strip()]
    headline = _safe(content.get("headline"))
    subheadline = _safe(content.get("subheadline"))
    palette = brand.get("palette") or PALETTES["default"]

    if not services:
        services = [category]
    if not service_areas and city:
        service_areas = [city]

    reputation = _reputation_text(rating, review_count)
    service_cards = "".join(
        f'<article class="service-card"><span>{index:02d}</span><h3>{_safe(service)}</h3><p>Professional service presented in a clearer, more conversion-focused format.</p></article>'
        for index, service in enumerate(services[:6], start=1)
    )
    areas = "".join(f"<li>{_safe(area)}</li>" for area in service_areas[:8])
    phone_cta = (
        f'<a class="button button-primary" href="{_safe(_phone_href(source.get("phone")))}">Call {phone}</a>'
        if phone
        else '<a class="button button-primary" href="#contact">Request service</a>'
    )
    reputation_block = (
        f'<div class="rating"><strong>{_safe(reputation)}</strong><span>Public Google reputation</span></div>'
        if reputation
        else ""
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><meta name="robots" content="noindex,nofollow,noarchive" /><meta name="referrer" content="no-referrer" /><title>{business_name} | Concept Homepage</title>
<style>:root{{--ink:{palette['ink']};--accent:{palette['accent']};--surface:{palette['surface']};--paper:#fff;--muted:#667078;--line:#dde2e5}}*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:var(--ink);line-height:1.55}}a{{color:inherit;text-decoration:none}}.wrap{{width:min(1160px,calc(100% - 40px));margin:0 auto}}.concept{{background:#0f1720;color:#dfe6ea;font-size:12px;text-align:center;padding:8px 16px}}header{{position:absolute;z-index:5;width:100%;padding:22px 0;color:#fff}}.nav{{display:flex;justify-content:space-between}}.brand{{font-weight:800}}.hero{{min-height:700px;display:grid;align-items:end;color:#fff;background:linear-gradient(115deg,#09141ff5,#23394d);padding:150px 0 76px}}.hero-grid{{display:grid;grid-template-columns:1.25fr .75fr;gap:64px;align-items:end}}.eyebrow{{color:#f4d494;font-size:13px;font-weight:800;text-transform:uppercase}}h1{{font-size:clamp(48px,7vw,84px);line-height:.98;margin:16px 0 24px}}.actions{{display:flex;gap:12px;margin-top:28px}}.button{{padding:14px 19px;border-radius:8px;font-weight:800}}.button-primary{{background:var(--accent);color:#111}}.button-secondary{{border:1px solid #ffffff66}}.rating{{border:1px solid #ffffff33;background:#ffffff12;padding:24px;border-radius:14px}}section{{padding:86px 0}}.services{{background:var(--surface)}}.service-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.service-card{{background:#fff;border:1px solid var(--line);padding:28px}}.areas{{background:#101b24;color:#fff}}.areas ul{{display:flex;flex-wrap:wrap;gap:10px;list-style:none}}.areas li{{border:1px solid #ffffff26;padding:9px 14px;border-radius:999px}}@media(max-width:800px){{.hero-grid,.service-grid{{grid-template-columns:1fr}}}}</style></head><body><div class="concept">Concept website prepared by LILOs Growth for demonstration purposes. Not affiliated with or endorsed by {business_name}.</div><header><div class="wrap nav"><div class="brand">{business_name}</div><small>{location}</small></div></header><main><section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">{category} · {location}</div><h1>{headline}</h1><p>{subheadline}</p><div class="actions">{phone_cta}<a class="button button-secondary" href="#services">Explore services</a></div></div>{reputation_block}</div></section><section id="services" class="services"><div class="wrap"><div class="service-grid">{service_cards}</div></div></section><section class="areas"><div class="wrap"><h2>Service area</h2><ul>{areas}</ul></div></section></main></body></html>"""


def render_demo_site(*, source: dict[str, Any], content: dict[str, Any], brand: dict[str, Any]) -> str:
    if brand.get("template_key") == "trade-modern-v1":
        return _render_v1(source=source, content=content, brand=brand)
    return _render_v2(source=source, content=content, brand=brand)
