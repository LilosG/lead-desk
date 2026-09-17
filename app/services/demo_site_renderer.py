from html import escape
from typing import Any


TEMPLATES = {
    "trade-modern-v1": {
        "name": "Trade Modern",
        "description": "High-trust home-service homepage with strong mobile CTA and reputation proof.",
    },
}


PALETTES = {
    "electrician": {"ink": "#132238", "accent": "#e4a72f", "surface": "#f4f6f8"},
    "plumber": {"ink": "#12324a", "accent": "#2f91c3", "surface": "#f2f7fa"},
    "hvac": {"ink": "#17303b", "accent": "#d66b36", "surface": "#f5f6f4"},
    "roofer": {"ink": "#272b2e", "accent": "#b65d3a", "surface": "#f5f3f0"},
    "default": {"ink": "#1f2a2e", "accent": "#a77a3d", "surface": "#f5f4f1"},
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


def render_demo_site(
    *,
    source: dict[str, Any],
    content: dict[str, Any],
    brand: dict[str, Any],
) -> str:
    business_name = _safe(source.get("name"))
    city = _safe(source.get("city"))
    state = _safe(source.get("state"))
    location = ", ".join(part for part in [city, state] if part)
    phone = _safe(source.get("phone"))
    category = _safe(source.get("primary_type_display") or "Home Service Professional")
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

    reputation = ""
    if rating is not None and review_count is not None:
        reputation = f"{float(rating):.1f} Google rating · {int(review_count):,} reviews"
    elif review_count is not None:
        reputation = f"{int(review_count):,} Google reviews"

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
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow,noarchive" />
  <meta name="referrer" content="no-referrer" />
  <title>{business_name} | Concept Homepage</title>
  <style>
    :root{{--ink:{palette['ink']};--accent:{palette['accent']};--surface:{palette['surface']};--paper:#fff;--muted:#667078;--line:#dde2e5;}}
    *{{box-sizing:border-box}} html{{scroll-behavior:smooth}} body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--paper);line-height:1.55}}
    a{{color:inherit;text-decoration:none}} .wrap{{width:min(1160px,calc(100% - 40px));margin:0 auto}}
    .concept{{background:#0f1720;color:#dfe6ea;font-size:12px;text-align:center;padding:8px 16px}}
    header{{position:absolute;z-index:5;width:100%;padding:22px 0;color:#fff}} .nav{{display:flex;align-items:center;justify-content:space-between;gap:24px}} .brand{{font-weight:800;font-size:20px;letter-spacing:-.02em}} .nav small{{opacity:.78}}
    .hero{{min-height:700px;display:grid;align-items:end;color:#fff;background:linear-gradient(115deg,rgba(9,20,31,.96) 8%,rgba(19,34,56,.84) 48%,rgba(19,34,56,.58) 100%),radial-gradient(circle at 85% 22%,{palette['accent']}88,transparent 38%),linear-gradient(135deg,{palette['ink']},#324759);padding:150px 0 76px}}
    .hero-grid{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:64px;align-items:end}} .eyebrow{{color:#f4d494;font-size:13px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}}
    h1{{font-size:clamp(48px,7vw,84px);line-height:.98;letter-spacing:-.055em;margin:16px 0 24px;max-width:880px}} .hero p{{font-size:19px;max-width:700px;color:#e4e9ec}}
    .actions{{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}} .button{{display:inline-flex;align-items:center;justify-content:center;padding:14px 19px;border-radius:8px;font-weight:800}} .button-primary{{background:var(--accent);color:#111}} .button-secondary{{border:1px solid #ffffff66;background:#ffffff12}}
    .rating{{border:1px solid #ffffff33;background:#ffffff12;backdrop-filter:blur(10px);padding:24px;border-radius:14px}} .rating strong{{display:block;font-size:23px}} .rating span{{color:#d3dade;font-size:13px}}
    .stats{{margin-top:-32px;position:relative;z-index:3}} .stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);background:#fff;border:1px solid var(--line);box-shadow:0 18px 45px #11223314}} .stat{{padding:24px 28px;border-right:1px solid var(--line)}} .stat:last-child{{border-right:0}} .stat strong{{display:block;font-size:18px}} .stat span{{font-size:13px;color:var(--muted)}}
    section{{padding:86px 0}} .section-head{{display:grid;grid-template-columns:.65fr 1.35fr;gap:32px;align-items:end;margin-bottom:38px}} .section-head h2{{font-size:clamp(34px,4vw,54px);line-height:1;letter-spacing:-.045em;margin:0}} .section-head p{{color:var(--muted);margin:0;max-width:700px}}
    .services{{background:var(--surface)}} .service-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}} .service-card{{background:#fff;border:1px solid var(--line);padding:28px;min-height:220px}} .service-card span{{font-size:12px;font-weight:800;color:var(--accent)}} .service-card h3{{font-size:24px;margin:28px 0 8px;letter-spacing:-.03em}} .service-card p{{margin:0;color:var(--muted)}}
    .trust-grid{{display:grid;grid-template-columns:1fr 1fr;gap:58px;align-items:center}} .visual{{min-height:430px;border-radius:16px;background:linear-gradient(145deg,{palette['ink']},#526671);position:relative;overflow:hidden}} .visual:after{{content:"";position:absolute;inset:12%;border:1px solid #ffffff2e;border-radius:999px;box-shadow:0 0 0 80px #ffffff08}}
    .trust h2{{font-size:48px;line-height:1.03;letter-spacing:-.045em;margin:0 0 20px}} .checks{{display:grid;gap:14px;margin:28px 0}} .check{{display:flex;gap:12px;align-items:flex-start}} .check b{{display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:var(--surface);color:var(--accent)}}
    .areas{{background:#101b24;color:#fff}} .areas-grid{{display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:center}} .areas h2{{font-size:48px;line-height:1.02;letter-spacing:-.04em;margin:0 0 18px}} .areas ul{{display:flex;flex-wrap:wrap;gap:10px;padding:0;list-style:none}} .areas li{{border:1px solid #ffffff26;background:#ffffff0d;border-radius:999px;padding:9px 14px}}
    .cta{{padding:74px 0;background:var(--accent)}} .cta-grid{{display:flex;justify-content:space-between;align-items:center;gap:30px}} .cta h2{{font-size:42px;line-height:1;margin:0;letter-spacing:-.04em}} .cta .button{{background:#101820;color:#fff}}
    footer{{padding:32px 0;color:var(--muted);font-size:13px}} .footer-grid{{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}}
    .mobile-call{{display:none;position:fixed;bottom:14px;left:14px;right:14px;z-index:20;background:var(--accent);color:#111;padding:14px;border-radius:10px;text-align:center;font-weight:900;box-shadow:0 14px 35px #0004}}
    @media(max-width:800px){{.hero{{min-height:660px;padding-top:130px}}.hero-grid,.trust-grid,.areas-grid,.section-head{{grid-template-columns:1fr;gap:26px}}.hero-grid{{gap:28px}}.service-grid{{grid-template-columns:1fr}}.stats-grid{{grid-template-columns:1fr}}.stat{{border-right:0;border-bottom:1px solid var(--line)}}.stat:last-child{{border-bottom:0}}section{{padding:64px 0}}.cta-grid{{align-items:flex-start;flex-direction:column}}.mobile-call{{display:block}}body{{padding-bottom:72px}}}}
  </style>
</head>
<body>
  <div class="concept">Concept website prepared by LILOs Growth for demonstration purposes. Not affiliated with or endorsed by {business_name}.</div>
  <header><div class="wrap nav"><div class="brand">{business_name}</div><small>{location}</small></div></header>
  <main>
    <section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">{category} · {location}</div><h1>{headline}</h1><p>{subheadline}</p><div class="actions">{phone_cta}<a class="button button-secondary" href="#services">Explore services</a></div></div>{reputation_block}</div></section>
    <div class="stats"><div class="wrap stats-grid"><div class="stat"><strong>{business_name}</strong><span>Local business concept</span></div><div class="stat"><strong>{category}</strong><span>Primary business category</span></div><div class="stat"><strong>{location or 'Local service area'}</strong><span>Community-focused presentation</span></div></div></div>
    <section id="services" class="services"><div class="wrap"><div class="section-head"><h2>Services made easier to understand.</h2><p>A focused homepage should quickly show customers what the business does, where it works, and how to take the next step.</p></div><div class="service-grid">{service_cards}</div></div></section>
    <section class="trust"><div class="wrap trust-grid"><div class="visual" aria-hidden="true"></div><div><div class="eyebrow">Built around trust</div><h2>A stronger first impression for local customers.</h2><p>This concept brings the business name, local relevance, reputation signals, services, and contact path together in one clear mobile-first experience.</p><div class="checks"><div class="check"><b>✓</b><span>Clear business and location context</span></div><div class="check"><b>✓</b><span>Visible reputation proof using public aggregate data</span></div><div class="check"><b>✓</b><span>Fast path to call or request service</span></div></div></div></div></section>
    <section class="areas"><div class="wrap areas-grid"><div><div class="eyebrow">Service area</div><h2>Built to feel local.</h2><p>Areas shown here come from the information confirmed for this demo and can be expanded before a production launch.</p></div><ul>{areas}</ul></div></section>
    <section id="contact" class="cta"><div class="wrap cta-grid"><div><div class="eyebrow" style="color:#191919">Next step</div><h2>Make it easy to choose {business_name}.</h2></div>{phone_cta}</div></section>
  </main>
  <footer><div class="wrap footer-grid"><strong>{business_name}</strong><span>{phone} · {location}</span><span>Concept website by LILOs Growth</span></div></footer>
  {f'<a class="mobile-call" href="{_safe(_phone_href(source.get("phone")))}">Call {phone}</a>' if phone else ''}
</body>
</html>"""
