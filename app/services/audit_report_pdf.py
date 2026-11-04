"""Audit report PDF.

Layout, built for a business owner who opens the attachment once:
  page 1  dark cover band, an at-a-glance scorecard (Google profile, Reviews,
          Website, Mobile speed), the short version, two charts (reviews vs.
          local competitors, mobile speed meter) and the top three fixes;
  page 2+ local benchmark, how the homepage looks in Google, content gaps,
          AI search readiness and how the site is built;
  then    action-plan checklist, what's working, and one card per item with the
          key number called out, then next step.

Older snapshots (no impact / measurements) still render; missing pieces are
skipped rather than guessed.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

BRAND = "Lilos Growth"

INK = colors.HexColor("#1f211d")
MUTED = colors.HexColor("#6f7169")
FAINT = colors.HexColor("#9a9b94")
LINE = colors.HexColor("#e2dfd6")
SURFACE = colors.HexColor("#f6f4ef")
DARK = colors.HexColor("#22241f")
GOLD = colors.HexColor("#9a7a3f")
GOLD_LIGHT = colors.HexColor("#c9ad73")
WHITE = colors.white

RED = colors.HexColor("#b4432f")
RED_BG = colors.HexColor("#f8e6e2")
AMBER = colors.HexColor("#b97d1c")
AMBER_BG = colors.HexColor("#f8eedb")
GREEN = colors.HexColor("#2f7a4f")
GREEN_BG = colors.HexColor("#e4f2e9")
GREY = colors.HexColor("#8b8d86")
GREY_BG = colors.HexColor("#efeee9")

PAGE_W, PAGE_H = letter
MARGIN = 0.6 * inch
CONTENT_W = PAGE_W - 2 * MARGIN
COVER_BAND_H = 1.95 * inch

TONES = {
    "red": (RED, RED_BG),
    "amber": (AMBER, AMBER_BG),
    "green": (GREEN, GREEN_BG),
    "grey": (GREY, GREY_BG),
}
IMPACT_TONE = {"high": "red", "medium": "amber", "low": "green"}
IMPACT_TEXT = {"high": "High impact", "medium": "Medium impact", "low": "Quick win"}
_LEGACY_IMPACT = {"recommended": "medium", "review_required": "medium", "optional": "low"}

REVIEW_SIGNALS = {
    "reviews_bottom_quartile", "reviews_below_median", "no_reviews",
    "no_review_replies", "few_review_replies",
}
SPEED_SIGNALS = {"psi_mobile_critical", "psi_mobile_poor"}
WEBSITE_DOWN_SIGNALS = {"no_website", "site_down", "broken_profile_link", "website_not_on_gbp"}


# ---------------------------------------------------------------- helpers

def _text(value: object) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _pretty_date(value: object) -> str:
    if not value:
        return ""
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return raw


def _int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _impact(finding: dict[str, Any]) -> str:
    impact = finding.get("impact")
    if impact in IMPACT_TONE:
        return impact
    return _LEGACY_IMPACT.get(finding.get("disposition") or "", "medium")


def _short_url(url: str | None) -> str:
    text = (url or "").strip()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.startswith("www."):
        text = text[4:]
    return text.rstrip("/")


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK)

    def s(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base, **kw)

    return {
        "body": s("body"),
        "body_lg": s("body_lg", fontSize=10.2, leading=14.6),
        "muted": s("muted", fontSize=8, leading=10.8, textColor=MUTED),
        "small": s("small", fontSize=7.4, leading=9.6, textColor=MUTED),
        "kicker": s("kicker", fontName="Helvetica-Bold", fontSize=7, leading=9,
                    textColor=GOLD, spaceAfter=2),
        "h2": s("h2", fontName="Helvetica-Bold", fontSize=15, leading=18, spaceAfter=6),
        "h3": s("h3", fontName="Helvetica-Bold", fontSize=11.2, leading=13.8),
        "row_title": s("row_title", fontName="Helvetica-Bold", fontSize=9.4, leading=11.8),
        "row_text": s("row_text", fontSize=8.2, leading=10.8, textColor=MUTED),
        "label": s("label", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5,
                   textColor=FAINT),
        "tile_area": s("tile_area", fontName="Helvetica-Bold", fontSize=7, leading=9,
                       textColor=MUTED),
        "tile_status": s("tile_status", fontName="Helvetica-Bold", fontSize=12.5, leading=14.5),
        "tile_detail": s("tile_detail", fontSize=7.8, leading=10, textColor=MUTED),
        "stat": s("stat", fontName="Helvetica-Bold", fontSize=20, leading=22,
                  alignment=TA_CENTER),
        "stat_label": s("stat_label", fontSize=7, leading=8.8, textColor=MUTED,
                        alignment=TA_CENTER),
        "num": s("num", fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=WHITE,
                 alignment=TA_CENTER),
        "cta_title": s("cta_title", fontName="Helvetica-Bold", fontSize=13, leading=16,
                       textColor=WHITE),
        "cta_body": s("cta_body", fontSize=9.4, leading=13.2, textColor=colors.HexColor("#e6e4dc")),
        "cta_small": s("cta_small", fontSize=8, leading=11, textColor=GOLD_LIGHT),
    }


def _pill(text: str, tone: str, style: ParagraphStyle) -> Table:
    fg, bg = TONES[tone]
    para = Paragraph(
        _text(text),
        ParagraphStyle(f"pill-{tone}", parent=style, fontName="Helvetica-Bold", fontSize=6.8,
                       leading=8, textColor=fg, alignment=TA_CENTER),
    )
    t = Table([[para]], colWidths=[0.95 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _section(title: str, kicker: str, st: dict[str, ParagraphStyle]) -> list[Flowable]:
    return [Paragraph(_text(kicker.upper()), st["kicker"]), Paragraph(_text(title), st["h2"])]


# ---------------------------------------------------------------- drawings

class ReviewBars(Flowable):
    """Horizontal bars: this business vs. the local typical vs. the leader."""

    def __init__(self, rows: list[tuple[str, int, bool]], width: float):
        super().__init__()
        self.rows = rows
        self.width = width
        self.row_h = 24
        self.height = self.row_h * len(rows)

    def wrap(self, *_: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        num_w = 0.45 * inch
        bar_w = self.width - num_w
        top = max((value for _, value, _ in self.rows), default=1) or 1
        for i, (label, value, is_you) in enumerate(self.rows):
            y = self.height - (i + 1) * self.row_h + 2
            font = "Helvetica-Bold" if is_you else "Helvetica"
            c.setFont(font, 7.6)
            c.setFillColor(INK if is_you else MUTED)
            text = label
            while text and c.stringWidth(text, font, 7.6) > bar_w:
                text = text[:-2] + "…"
            c.drawString(0, y + 11, text)
            c.setFillColor(GREY_BG)
            c.roundRect(0, y, bar_w, 8, 2.5, stroke=0, fill=1)
            c.setFillColor(GOLD if is_you else colors.HexColor("#b9b6ab"))
            c.roundRect(0, y, max(3.0, bar_w * value / top), 8, 2.5, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 9)
            c.drawRightString(self.width, y, f"{value:,}")


class SpeedMeter(Flowable):
    """0-100 band with Google's red / orange / green ranges and a marker."""

    def __init__(self, score: int, width: float, lcp_ms: Any = None):
        super().__init__()
        self.score = max(0, min(100, score))
        self.lcp = lcp_ms
        self.width = width
        self.height = 74

    def wrap(self, *_: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        tone = RED if self.score < 50 else AMBER if self.score < 90 else GREEN
        c.setFillColor(tone)
        c.setFont("Helvetica-Bold", 26)
        c.drawString(0, self.height - 26, str(self.score))
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 9)
        c.drawString(c.stringWidth(str(self.score), "Helvetica-Bold", 26) + 4,
                     self.height - 26, "/ 100")
        if self.lcp:
            try:
                secs = float(self.lcp) / 1000
                c.setFont("Helvetica", 8)
                c.drawRightString(self.width, self.height - 24,
                                  f"Main content shown after {secs:.1f}s")
            except (TypeError, ValueError):
                pass
        bar_y = 22
        zones = [(0, 50, RED), (50, 90, AMBER), (90, 100, GREEN)]
        for start, end, color in zones:
            c.setFillColor(color)
            c.setFillAlpha(0.85)
            c.rect(self.width * start / 100, bar_y, self.width * (end - start) / 100, 8,
                   stroke=0, fill=1)
        c.setFillAlpha(1)
        x = self.width * self.score / 100
        c.setFillColor(INK)
        p = c.beginPath()
        p.moveTo(x, bar_y + 9)
        p.lineTo(x - 5, bar_y + 17)
        p.lineTo(x + 5, bar_y + 17)
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        c.setFont("Helvetica", 6.8)
        c.setFillColor(MUTED)
        c.drawString(0, bar_y - 11, "Slow (0-49)")
        c.drawCentredString(self.width * 0.7, bar_y - 11, "Needs work (50-89)")
        c.drawRightString(self.width, bar_y - 11, "Fast (90+)")


class CheckBox(Flowable):
    def __init__(self, size: float = 9):
        super().__init__()
        self.size = size

    def wrap(self, *_: Any) -> tuple[float, float]:
        return self.size, self.size

    def draw(self) -> None:
        self.canv.setStrokeColor(FAINT)
        self.canv.setLineWidth(0.9)
        self.canv.roundRect(0, 0, self.size, self.size, 1.5, stroke=1, fill=0)


class CheckMark(Flowable):
    def __init__(self, size: float = 9):
        super().__init__()
        self.size = size

    def wrap(self, *_: Any) -> tuple[float, float]:
        return self.size, self.size

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(GREEN)
        c.circle(self.size / 2, self.size / 2, self.size / 2, stroke=0, fill=1)
        c.setStrokeColor(WHITE)
        c.setLineWidth(1.3)
        c.line(self.size * 0.27, self.size * 0.52, self.size * 0.44, self.size * 0.33)
        c.line(self.size * 0.44, self.size * 0.33, self.size * 0.75, self.size * 0.7)


# ---------------------------------------------------------------- content logic

def _scorecard(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    business = snapshot.get("business") or {}
    findings = snapshot.get("findings") or []
    measurements = snapshot.get("measurements") or {}
    comparison = snapshot.get("market_comparison") or {}
    signals = {f.get("signal") for f in findings}

    def worst(items: list[dict[str, Any]]) -> str | None:
        impacts = {_impact(f) for f in items}
        for level in ("high", "medium", "low"):
            if level in impacts:
                return level
        return None

    def from_findings(items: list[dict[str, Any]], ok_detail: str) -> tuple[str, str, str]:
        level = worst(items)
        n = len(items)
        if level is None:
            return "No issues flagged", ok_detail, "green"
        status = "Needs work" if level == "high" else "Room to improve"
        return status, f"{n} item{'s' if n != 1 else ''} to fix", "red" if level == "high" else "amber"

    tiles: list[dict[str, str]] = []

    # Google profile
    profile = [f for f in findings if f.get("category") == "Google Business Profile"
               and f.get("signal") not in REVIEW_SIGNALS | WEBSITE_DOWN_SIGNALS]
    status, detail, tone = from_findings(profile, "Nothing flagged in this audit")
    tiles.append({"area": "GOOGLE PROFILE", "status": status, "detail": detail, "tone": tone})

    # Reviews
    reviews = [f for f in findings if f.get("signal") in REVIEW_SIGNALS
               or f.get("category") == "Reputation"]
    status, detail, tone = from_findings(reviews, "")
    count = _int(business.get("review_count"))
    median = _int(comparison.get("median_reviews"))
    if count is not None and median:
        detail = f"{count:,} vs. {median:,} typical locally"
    elif count is not None:
        rating = business.get("rating")
        detail = f"{count:,} reviews" + (f", {float(rating):.1f} stars" if rating is not None else "")
    tiles.append({"area": "REVIEWS", "status": status, "detail": detail, "tone": tone})

    # Website
    has_site = bool(business.get("website_url")) and "no_website" not in signals
    if not has_site:
        tiles.append({"area": "WEBSITE", "status": "No website", "tone": "red",
                      "detail": "Nothing linked on Google"})
    elif "website_not_on_gbp" in signals:
        tiles.append({"area": "WEBSITE", "status": "Not on Google", "tone": "red",
                      "detail": "Site exists, listing doesn't link it"})
    elif "site_down" in signals:
        tiles.append({"area": "WEBSITE", "status": "Not loading", "tone": "red",
                      "detail": "Error page when checked"})
    elif "broken_profile_link" in signals:
        tiles.append({"area": "WEBSITE", "status": "Broken link", "tone": "red",
                      "detail": "Google's link leads to an error"})
    else:
        site = [f for f in findings if f.get("category") in {"Website", "Consistency"}
                and f.get("signal") not in SPEED_SIGNALS]
        status, detail, tone = from_findings(site, "Nothing flagged in this audit")
        tiles.append({"area": "WEBSITE", "status": status, "detail": detail, "tone": tone})

    # Mobile speed
    score = _int(measurements.get("mobile_speed"))
    if score is None:
        for f in findings:
            if f.get("signal") in SPEED_SIGNALS:
                score = _int((f.get("data") or {}).get("psi_performance"))
    if not has_site or "site_down" in signals:
        tiles.append({"area": "MOBILE SPEED", "status": "Not tested", "tone": "grey",
                      "detail": "No working site to test"})
    elif score is not None:
        tone = "red" if score < 50 else "amber" if score < 90 else "green"
        status = {"red": "Slow", "amber": "Could be faster", "green": "Fast"}[tone]
        tiles.append({"area": "MOBILE SPEED", "status": status, "tone": tone,
                      "detail": f"{score}/100 on Google's test"})
    elif SPEED_SIGNALS & signals:
        tiles.append({"area": "MOBILE SPEED", "status": "Slow", "tone": "red",
                      "detail": "Low score on Google's test"})
    else:
        tiles.append({"area": "MOBILE SPEED", "status": "Not tested", "tone": "grey",
                      "detail": "Speed test didn't run"})

    # AI search
    ai = snapshot.get("ai_readiness") or {}
    if ai.get("total"):
        share = ai["passed"] / ai["total"]
        tone = "green" if share == 1 else "amber" if share >= 0.6 else "red"
        tiles.append({"area": "AI SEARCH", "status": f"{ai['passed']} of {ai['total']} ready",
                      "detail": "Can AI tools read your site?", "tone": tone})
    return tiles


def _speed(snapshot: dict[str, Any]) -> tuple[int | None, Any]:
    m = snapshot.get("measurements") or {}
    score, lcp = _int(m.get("mobile_speed")), m.get("lcp_ms")
    if score is None:
        for f in snapshot.get("findings") or []:
            data = f.get("data") or {}
            if f.get("signal") in SPEED_SIGNALS and data.get("psi_performance") is not None:
                return _int(data["psi_performance"]), data.get("lcp_ms")
    return score, lcp


def _key_stat(finding: dict[str, Any]) -> tuple[str, str] | None:
    data = finding.get("data") or {}
    signal = finding.get("signal")
    if signal in SPEED_SIGNALS and data.get("psi_performance") is not None:
        return f"{_int(data['psi_performance'])}/100", "Google mobile speed score"
    if signal in {"reviews_bottom_quartile", "reviews_below_median"}:
        reviews, median = _int(data.get("reviews")), _int(data.get("median"))
        if reviews is not None and median:
            return f"{reviews:,} vs {median:,}", "your reviews vs. the local typical"
    if signal == "no_reviews":
        return "0", "Google reviews"
    if signal == "thin_content" and data.get("word_count") is not None:
        return f"{_int(data['word_count']):,}", "words on the homepage"
    if signal == "few_photos" and data.get("photo_count") is not None:
        return str(_int(data["photo_count"])), "photos on Google"
    if signal in {"site_down", "broken_profile_link"} and data.get("http_status"):
        return str(data["http_status"]), "error code returned"
    return None


# ---------------------------------------------------------------- page parts

def _tiles_table(tiles: list[dict[str, str]], st: dict[str, ParagraphStyle]) -> Table:
    gap = 6
    w = (CONTENT_W - gap * (len(tiles) - 1)) / len(tiles)
    cells, widths = [], []
    for i, tile in enumerate(tiles):
        fg, _bg = TONES[tile["tone"]]
        inner = Table(
            [
                [Paragraph(_text(tile["area"]), st["tile_area"])],
                [Paragraph(_text(tile["status"]), ParagraphStyle(
                    f"ts{i}", parent=st["tile_status"], textColor=fg,
                    fontSize=11 if len(tiles) > 4 else 12.5, leading=13 if len(tiles) > 4 else 14.5))],
                [Paragraph(_text(tile.get("detail") or ""), st["tile_detail"])],
            ],
            colWidths=[w],
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("LINEABOVE", (0, 0), (-1, 0), 3.5, fg),
            ("LEFTPADDING", (0, 0), (-1, -1), 7 if len(tiles) > 4 else 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 if len(tiles) > 4 else 6),
            ("TOPPADDING", (0, 0), (-1, 0), 9),
            ("TOPPADDING", (0, 1), (-1, -1), 1),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ]))
        cells.append(inner)
        widths.append(w)
        if i < len(tiles) - 1:
            cells.append("")
            widths.append(gap)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _chart_panel(title: str, subtitle: str, chart: Flowable, width: float,
                 st: dict[str, ParagraphStyle]) -> Table:
    t = Table(
        [[Paragraph(_text(title), st["row_title"])],
         [Paragraph(_text(subtitle), st["small"])],
         [Spacer(1, 4)],
         [chart]],
        colWidths=[width],
    )
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, 0), 10), ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -2), 1),
    ]))
    return t


def _charts(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> Flowable | None:
    business = snapshot.get("business") or {}
    comparison = snapshot.get("market_comparison") or {}
    panels: list[tuple[str, str, Any]] = []

    count = _int(business.get("review_count"))
    median = _int(comparison.get("median_reviews"))
    if count is not None and median:
        rows = [("You", count, True), (f"Typical in {comparison.get('market') or 'your area'}", median, False)]
        leaders = comparison.get("leaders") or []
        if leaders and _int(leaders[0].get("review_count")):
            rows.append((f"Most reviewed: {leaders[0].get('name')}", _int(leaders[0]["review_count"]), False))
        sample = comparison.get("sample_size")
        panels.append((
            "Google reviews vs. local competitors",
            f"Based on {sample} comparable {comparison.get('niche') or 'local'} businesses nearby."
            if sample else "Based on comparable businesses nearby.",
            lambda w, rows=rows: ReviewBars(rows, w),
        ))

    score, lcp = _speed(snapshot)
    if score is not None:
        panels.append((
            "Mobile speed",
            "Google PageSpeed Insights, homepage on a phone.",
            lambda w, score=score, lcp=lcp: SpeedMeter(score, w, lcp),
        ))

    if not panels:
        return None
    gap = 10
    pw = (CONTENT_W - gap * (len(panels) - 1)) / len(panels)
    built = [_chart_panel(t, s, make(pw - 22), pw, st) for t, s, make in panels]
    cells, widths = [], []
    for i, b in enumerate(built):
        cells.append(b)
        widths.append(pw)
        if i < len(built) - 1:
            cells.append("")
            widths.append(gap)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _number_badge(n: int, st: dict[str, ParagraphStyle], tone: Any = GOLD) -> Table:
    t = Table([[Paragraph(str(n), st["num"])]], colWidths=[0.34 * inch], rowHeights=[0.34 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tone),
        ("ROUNDEDCORNERS", [12, 12, 12, 12]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _moves_section(moves: list[dict[str, str]], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    rows = [
        [_number_badge(i, st),
         [Paragraph(_text(m.get("move")), st["row_title"]), Spacer(1, 2),
          Paragraph(_text(m.get("why")), st["body"])]]
        for i, m in enumerate(moves, start=1)
    ]
    t = Table(rows, colWidths=[0.5 * inch, CONTENT_W - 0.5 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return [
        *_section("What I'd do first", "Start here", st),
        t, Spacer(1, 4),
        Paragraph("The rest of this report is the full picture. If you'd like to talk any of it "
                  "through, I'm happy to.", st["muted"]),
        Spacer(1, 14),
    ]


def _top_fixes(findings: list[dict[str, Any]], st: dict[str, ParagraphStyle]) -> Table:
    rows = []
    for i, f in enumerate(findings[:3], start=1):
        impact = _impact(f)
        rows.append([
            _number_badge(i, st, DARK),
            [Paragraph(_text(f.get("title")), st["row_title"]),
             Paragraph(_text(f.get("what_we_found")), st["row_text"])],
            _pill(IMPACT_TEXT[impact], IMPACT_TONE[impact], st["body"]),
        ])
    t = Table(rows, colWidths=[0.5 * inch, CONTENT_W - 0.5 * inch - 1.1 * inch, 1.1 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]))
    return t


def _action_plan(findings: list[dict[str, Any]], st: dict[str, ParagraphStyle]) -> Table:
    rows = [[
        "", Paragraph("#", st["label"]), Paragraph("WHAT TO FIX", st["label"]),
        Paragraph("WHERE", st["label"]), Paragraph("IMPACT", st["label"]),
    ]]
    for i, f in enumerate(findings, start=1):
        impact = _impact(f)
        rows.append([
            CheckBox(),
            Paragraph(f"{i:02d}", st["small"]),
            Paragraph(_text(f.get("title")), st["row_title"]),
            Paragraph(_text(f.get("category") or ""), st["row_text"]),
            _pill(IMPACT_TEXT[impact], IMPACT_TONE[impact], st["body"]),
        ])
    widths = [0.28 * inch, 0.34 * inch, CONTENT_W - 0.62 * inch - 1.55 * inch - 1.1 * inch,
              1.55 * inch, 1.1 * inch]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
    ]))
    return t


def _comparison_table(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    comparison = snapshot.get("market_comparison")
    if not comparison:
        return []
    you = comparison.get("business") or {}
    leaders = comparison.get("leaders") or []
    rows_data = [(you, True)] + [(item, False) for item in leaders]
    top = max((_int(r.get("review_count")) or 0 for r, _ in rows_data), default=1) or 1
    bar_w = 1.7 * inch
    header = [Paragraph(h, st["label"]) for h in ("BUSINESS", "RATING", "REVIEWS", "", "WEBSITE")]
    rows = [header]
    for item, is_you in rows_data:
        rating = item.get("rating")
        count = _int(item.get("review_count")) or 0
        name_style = ParagraphStyle("cmpname", parent=st["row_title"],
                                    textColor=INK if is_you else colors.HexColor("#3b3d37"),
                                    fontName="Helvetica-Bold" if is_you else "Helvetica")
        rows.append([
            Paragraph(_text(item.get("name")) + ("  <font color='#9a7a3f'>(you)</font>" if is_you else ""), name_style),
            Paragraph(f"{float(rating):.1f}" if rating is not None else "-", st["body"]),
            Paragraph(f"{count:,}", st["body"]),
            _MiniBar(count, top, bar_w, is_you),
            Paragraph("Yes" if item.get("has_website") else "No", st["body"]),
        ])
    widths = [CONTENT_W - 0.6 * inch - 0.7 * inch - bar_w - 0.2 * inch - 0.7 * inch,
              0.6 * inch, 0.7 * inch, bar_w + 0.2 * inch, 0.7 * inch]
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 1), (-1, 1), SURFACE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
    ]))
    market = comparison.get("market") or "your area"
    niche = comparison.get("niche") or "local"
    intro = (
        f"Public Google data for {comparison.get('sample_size')} comparable {niche} businesses in "
        f"{market}. The typical one has {_int(comparison.get('median_reviews')) or 0:,} reviews. "
        "The most-reviewed are shown for reference."
    )
    return [
        *_section(f"How you compare in {market}", "Local comparison", st),
        Paragraph(_text(intro), st["muted"]),
        Spacer(1, 6),
        KeepTogether(t),
        Spacer(1, 18),
    ]


class _MiniBar(Flowable):
    def __init__(self, value: int, top: int, width: float, is_you: bool):
        super().__init__()
        self.value, self.top, self.width, self.is_you = value, top, width, is_you
        self.height = 8

    def wrap(self, *_: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(GREY_BG)
        c.roundRect(0, 0, self.width, self.height, 2.5, stroke=0, fill=1)
        c.setFillColor(GOLD if self.is_you else colors.HexColor("#b9b6ab"))
        c.roundRect(0, 0, max(2.5, self.width * self.value / self.top), self.height, 2.5,
                    stroke=0, fill=1)


def _working(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    items = [i for i in snapshot.get("audit_scope") or [] if i.get("status") == "confirmed"]
    if not items:
        return []
    cells = [
        Table([[CheckMark(10), [Paragraph(_text(i.get("label")), st["row_title"]),
                                Paragraph(_text(i.get("value")), st["row_text"])]]],
              colWidths=[0.28 * inch, CONTENT_W / 2 - 0.4 * inch],
              style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (0, 0), 2)]))
        for i in items
    ]
    rows = [[cells[i], cells[i + 1] if i + 1 < len(cells) else ""] for i in range(0, len(cells), 2)]
    t = Table(rows, colWidths=[CONTENT_W / 2] * 2)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [*_section("What's already working", "Strengths", st), t]


def _finding_card(index: int, f: dict[str, Any], st: dict[str, ParagraphStyle]) -> Table:
    impact = _impact(f)
    fg, _bg = TONES[IMPACT_TONE[impact]]
    stat = _key_stat(f)
    stat_w = 1.35 * inch if stat else 0
    text_w = CONTENT_W - 0.22 * inch - stat_w

    header = Table(
        [[Paragraph(f"<font color='#9a9b94'>{index:02d}</font>&nbsp;&nbsp;{_text(f.get('title'))}", st["h3"]),
          _pill(IMPACT_TEXT[impact], IMPACT_TONE[impact], st["body"])]],
        colWidths=[text_w - 1.0 * inch, 1.0 * inch],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))

    found = _text(f.get("what_we_found"))
    evidence = f.get("evidence")
    if evidence and evidence not in (f.get("what_we_found") or ""):
        found += f" <font color='#6f7169'>{_text(evidence)}</font>"

    def block(label: str, html: str) -> list[Flowable]:
        return [Paragraph(label, st["label"]), Paragraph(html, st["body"]), Spacer(1, 5)]

    left: list[Flowable] = [
        header,
        Paragraph(_text(f.get("category") or ""), st["small"]),
        Spacer(1, 6),
        *block("WHAT WE FOUND", found),
        *block("WHY IT MATTERS", _text(f.get("why_it_matters"))),
        *block("HOW TO FIX IT", f"<font color='#9a7a3f'><b>&#8594;</b></font> {_text(f.get('recommendation'))}"),
    ]
    row = [left]
    widths = [text_w]
    if stat:
        big = ParagraphStyle("statc", parent=st["stat"], textColor=fg,
                             fontSize=20 if len(stat[0]) <= 7 else 15)
        stat_box = Table([[Paragraph(_text(stat[0]), big)], [Paragraph(_text(stat[1]), st["stat_label"])]],
                         colWidths=[stat_w - 0.15 * inch])
        stat_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        row.append(stat_box)
        widths.append(stat_w)
    body = Table([row], colWidths=widths)
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    card = Table([[body]], colWidths=[CONTENT_W])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 4, fg),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return card


def _next_step(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> Table | None:
    step = snapshot.get("next_step") or {}
    if not step.get("text"):
        return None
    parts: list[Flowable] = [
        Paragraph("Next step", st["cta_title"]),
        Spacer(1, 4),
        Paragraph(_text(step["text"]), st["cta_body"]),
    ]
    if step.get("demo_url"):
        url = _text(step["demo_url"])
        parts += [Spacer(1, 5), Paragraph(
            f"See a concept homepage we put together: <link href='{url}' color='#c9ad73'><u>{url}</u></link>",
            st["cta_body"])]
    parts += [Spacer(1, 8), Paragraph("Mike Prickett  |  Lilos Growth  |  lilosgrowth.com", st["cta_small"])]
    t = Table([[parts]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("LINEABOVE", (0, 0), (-1, 0), 3, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 18), ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 14), ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    return t


# ---------------------------------------------------------------- competitive sections

VERDICT = {"behind": ("Behind", "red"), "on_par": ("On par", "grey"), "ahead": ("Ahead", "green")}


def _benchmark_section(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    bench = snapshot.get("benchmarks") or {}
    rows_in = bench.get("rows") or []
    if not rows_in:
        return []
    comparison = snapshot.get("market_comparison") or {}
    market = comparison.get("market") or "your area"
    niche = comparison.get("niche") or "local"
    n = bench.get("sample_size") or 0
    head = [Paragraph(h, st["label"]) for h in ("", "YOU", "TYPICAL NEARBY", "BEST NEARBY", "")]
    rows = [head]
    for r in rows_in:
        word, tone = VERDICT.get(r.get("verdict"), ("On par", "grey"))
        metric = Paragraph(
            _text(r.get("metric")) + (f"<br/><font size='7' color='#9a9b94'>{_text(r['note'])}</font>"
                                      if r.get("note") else ""),
            st["row_title"],
        )
        fg = TONES[tone][0] if tone != "grey" else INK
        you_style = ParagraphStyle(f"you-{tone}", parent=st["row_title"], textColor=fg)
        rows.append([
            metric,
            Paragraph(_text(r.get("you")), you_style),
            Paragraph(_text(r.get("typical")), st["body"]),
            Paragraph(_text(r.get("best") or ""), st["body"]),
            _pill(word, tone, st["body"]),
        ])
    widths = [2.35 * inch, 1.2 * inch, 1.35 * inch, 1.25 * inch, CONTENT_W - 6.15 * inch]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
    ]))
    behind, total = bench.get("behind") or 0, len(rows_in)
    intro = (
        f"We compared {_text(snapshot.get('business', {}).get('name') or 'you')} with {n} other "
        f"{_text(niche)} businesses in {_text(market)}, using their public Google listings and websites. "
        + (f"You're behind on {behind} of {total} measures." if behind else
           "You're on par or ahead on every measure we compared.")
    )
    return [
        *_section("How you stack up locally", "Competitive benchmark", st),
        Paragraph(intro, st["muted"]),
        Spacer(1, 6),
        KeepTogether(t),
        Spacer(1, 18),
    ]


def _google_result(title: str | None, url: str, desc: str | None, st: dict[str, ParagraphStyle],
                   missing_title: str, missing_desc: str) -> list[Flowable]:
    t_style = ParagraphStyle("gtitle", parent=st["body"], fontSize=11.5, leading=14,
                             textColor=colors.HexColor("#1a0dab"))
    u_style = ParagraphStyle("gurl", parent=st["body"], fontSize=7.8, leading=10,
                             textColor=colors.HexColor("#3c7a52"))
    d_style = ParagraphStyle("gdesc", parent=st["body"], fontSize=8.4, leading=11.4,
                             textColor=colors.HexColor("#4d5156"))
    miss = ParagraphStyle("gmiss", parent=d_style, textColor=RED)
    return [
        Paragraph(_text(url), u_style),
        Paragraph(_text(title), t_style) if title else Paragraph(_text(missing_title), miss),
        Paragraph(_text(desc), d_style) if desc else Paragraph(_text(missing_desc), miss),
    ]


def _snippet_section(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    snip = snapshot.get("search_snippet") or {}
    shot = (snapshot.get("measurements") or {}).get("screenshot")
    if not snip and not shot:
        return []
    image = None
    if isinstance(shot, str) and "," in shot:
        try:
            import base64
            from reportlab.lib.utils import ImageReader
            from reportlab.platypus import Image

            raw = base64.b64decode(shot.split(",", 1)[1])
            iw, ih = ImageReader(BytesIO(raw)).getSize()
            w = 1.75 * inch
            h = min(w * ih / iw, 3.6 * inch)
            image = Table([[Image(BytesIO(raw), width=h * iw / ih, height=h)],
                           [Paragraph("Your homepage on a phone, as Google's speed test saw it.",
                                      st["stat_label"])]], colWidths=[w + 0.2 * inch])
            image.setStyle(TableStyle([
                ("BOX", (0, 0), (0, 0), 0.6, LINE), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
        except Exception:
            image = None

    text_w = CONTENT_W - 2.2 * inch if image is not None else CONTENT_W

    def card(label: str, body: list[Flowable], tone: Any) -> Table:
        c = Table([[Paragraph(label, st["label"])], [body]], colWidths=[text_w])
        c.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("LINEBEFORE", (0, 0), (0, -1), 3, tone),
            ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
        ]))
        return c

    blocks: list[Flowable] = []
    if snip:
        now = _google_result(snip.get("current_title"), snip.get("url") or "", snip.get("current_description"), st,
                             "No page title set, so Google writes its own headline.",
                             "No description set, so Google pulls a random line from the page.")
        new = _google_result(snip.get("suggested_title"), snip.get("url") or "",
                             snip.get("suggested_description"), st, "", "")
        blocks = [
            card("WHAT GOOGLE SHOWS FOR YOUR HOMEPAGE NOW", now, FAINT), Spacer(1, 8),
            card("SUGGESTED, WRITTEN FROM YOUR OWN BUSINESS DETAILS", new, GREEN), Spacer(1, 6),
            Paragraph("The title is the blue headline people click in search results; keep it under about "
                      "60 characters. The description is the grey text underneath. It doesn't change "
                      "rankings directly, but it's your pitch for the click.", st["small"]),
        ]

    title = "Your homepage in Google search" if snip else "Your homepage on a phone"
    out: list[Flowable] = [*_section(title, "How people see you", st)]
    if image is not None and blocks:
        t = Table([[image, blocks]], colWidths=[2.2 * inch, text_w])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        out.append(t)
    elif image is not None:
        out.append(image)
    else:
        out += blocks
    return out + [Spacer(1, 18)]


def _gaps_section(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    gaps = snapshot.get("page_gaps") or {}
    items = gaps.get("gaps") or []
    if not items:
        return []
    n = gaps.get("sample_size") or 0
    label = gaps.get("offering_label") or "service pages"
    rows = []
    for g in items:
        rows.append([
            Paragraph(_text(g.get("label")), st["row_title"]),
            _MiniBar(int(g.get("count") or 0), n or 1, 2.4 * inch, False),
            Paragraph(f"{int(g.get('count') or 0)} of {n} competitors", st["row_text"]),
        ])
    t = Table(rows, colWidths=[CONTENT_W - 2.6 * inch - 1.5 * inch, 2.6 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    yours = gaps.get("yours") or []
    have = ("Pages we found linked from your homepage: " + ", ".join(_text(y) for y in yours) + "."
            if yours else f"We didn't find any separate {_text(label)} linked from your homepage.")
    return [KeepTogether([
        *_section("Pages your competitors have that you don't", "Content gap", st),
        Paragraph(
            "Each of these has its own page on many competitors' sites (linked from their homepage) "
            "but not on yours. A dedicated page is what lets you show up when someone searches for "
            "that exact thing in your area.", st["muted"]),
        Spacer(1, 6),
        t,
        Spacer(1, 5),
        Paragraph(have, st["small"]),
    ]), Spacer(1, 18)]


AI_STATUS = {"pass": ("Ready", "green"), "fail": ("Fix", "red"),
             "review": ("Review", "amber"), "not_checked": ("Not checked", "grey")}


def _ai_section(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    ai = snapshot.get("ai_readiness") or {}
    checks = ai.get("checks") or []
    if not checks:
        return []
    rows = []
    for check in checks:
        word, tone = AI_STATUS.get(check.get("status"), AI_STATUS["not_checked"])
        rows.append([
            [Paragraph(_text(check.get("label")), st["row_title"]),
             Paragraph(_text(check.get("detail")), st["row_text"])],
            _pill(word, tone, st["body"]),
        ])
    t = Table(rows, colWidths=[CONTENT_W - 1.1 * inch, 1.1 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    return [KeepTogether([
        *_section("Is your site ready for AI search?", "AI search", st),
        Paragraph(
            "ChatGPT, Google's AI Overviews and similar tools answer questions using what they can "
            "read on the web. These checks show whether they can read and understand your site. "
            "They don't show whether you're mentioned today, and no one can guarantee that.",
            st["muted"]),
        Spacer(1, 6),
        t,
    ]), Spacer(1, 18)]


def _structure_section(snapshot: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Flowable]:
    site = snapshot.get("site_structure") or {}
    if not site:
        return []

    def stat(value: Any, label: str) -> list[Flowable]:
        return [Paragraph(_text(value), st["stat"]), Paragraph(_text(label), st["stat_label"])]

    stats = [stat(site.get("offering_pages") or 0,
                  "service page" if site.get("offering_pages") == 1 else "service pages"),
             stat(site.get("location_pages") or 0, "location pages"),
             stat(site.get("service_city_pages") or 0, "service + town pages")]
    if site.get("total_pages"):
        stats.insert(0, stat(site["total_pages"], "pages in your sitemap"))
    width = CONTENT_W / len(stats)
    numbers = Table([stats], colWidths=[width] * len(stats))
    numbers.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    parts: list[Flowable] = [
        *_section("How your site is built", "Site structure", st),
        Paragraph("Local searches are often for one service in one town. These counts show how many "
                  "pages you have for that.", st["muted"]),
        Spacer(1, 6),
        numbers,
    ]
    examples = site.get("examples") or []
    if examples:
        parts += [Spacer(1, 5), Paragraph(
            "Examples we found: " + ", ".join(_text(e) for e in examples), st["small"])]
    samples = site.get("samples") or []
    if samples:
        rows = [[Paragraph(h, st["label"]) for h in ("PAGE WE READ", "WORDS", "NAMES YOUR TOWN")]]
        for page in samples:
            names = bool(page.get("names_location"))
            rows.append([
                Paragraph(_text(page.get("path")), st["row_text"]),
                Paragraph(f"{int(page.get('words') or 0):,}", st["body"]),
                _pill("Yes" if names else "No", "green" if names else "amber", st["body"]),
            ])
        t = Table(rows, colWidths=[CONTENT_W - 2.1 * inch, 0.9 * inch, 1.2 * inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]))
        parts += [Spacer(1, 8), t]
    return [KeepTogether(parts), Spacer(1, 18)]


# ---------------------------------------------------------------- render

def render_audit_report_pdf(report: dict) -> bytes:
    snapshot = report["snapshot"]
    business = snapshot.get("business") or {}
    findings = list(snapshot.get("findings") or [])
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order[_impact(f)])
    st = _styles()

    name = business.get("name") or "Your business"
    checked = _pretty_date(snapshot.get("source_checked_at"))
    meta = "  ·  ".join(p for p in [business.get("location"), _short_url(business.get("website_url"))] if p)

    buffer = BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=0.55 * inch, bottomMargin=0.6 * inch,
        title=report.get("title") or f"Local Visibility Audit - {name}", author=BRAND,
    )

    def cover(c: Any, _doc: Any) -> None:
        c.saveState()
        c.setFillColor(DARK)
        c.rect(0, PAGE_H - COVER_BAND_H, PAGE_W, COVER_BAND_H, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.rect(0, PAGE_H - COVER_BAND_H - 3, PAGE_W, 3, stroke=0, fill=1)
        top = PAGE_H - 0.5 * inch
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(GOLD_LIGHT)
        c.drawString(MARGIN, top, "LILOS GROWTH")
        c.setFillColor(colors.HexColor("#b8b8b0"))
        c.setFont("Helvetica", 8)
        c.drawRightString(PAGE_W - MARGIN, top, f"LOCAL VISIBILITY AUDIT{'  ·  ' + checked.upper() if checked else ''}")
        c.setFillColor(WHITE)
        size = 26 if len(name) <= 34 else 21 if len(name) <= 46 else 17
        c.setFont("Helvetica-Bold", size)
        c.drawString(MARGIN, top - 0.62 * inch, name[:70])
        c.setFont("Helvetica", 9.5)
        c.setFillColor(colors.HexColor("#cfcfc8"))
        c.drawString(MARGIN, top - 0.62 * inch - 20, meta)
        _footer(c)
        c.restoreState()

    def later(c: Any, _doc: Any) -> None:
        c.saveState()
        c.setFillColor(GOLD)
        c.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(GOLD)
        c.drawString(MARGIN, PAGE_H - 0.36 * inch, "LILOS GROWTH")
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.36 * inch, f"Local Visibility Audit  ·  {name}")
        _footer(c)
        c.restoreState()

    def _footer(c: Any) -> None:
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(MARGIN, 0.42 * inch, PAGE_W - MARGIN, 0.42 * inch)
        c.setFont("Helvetica", 6.8)
        c.setFillColor(FAINT)
        c.drawString(MARGIN, 0.28 * inch, f"Prepared by {BRAND}  ·  lilosgrowth.com"
                     + (f"  ·  Checked {checked}" if checked else ""))
        c.drawRightString(PAGE_W - MARGIN, 0.28 * inch, f"Page {c.getPageNumber()}")

    cover_frame = Frame(MARGIN, 0.6 * inch, CONTENT_W,
                        PAGE_H - COVER_BAND_H - 0.25 * inch - 0.6 * inch, id="cover",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    body_frame = Frame(MARGIN, 0.6 * inch, CONTENT_W, PAGE_H - 0.6 * inch - 0.6 * inch, id="body",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=cover),
        PageTemplate(id="body", frames=[body_frame], onPage=later),
    ])

    story: list[Flowable] = [NextPageTemplate("body")]

    # Page 1 -------------------------------------------------------------
    story += [Paragraph("AT A GLANCE", st["kicker"]), Spacer(1, 2),
              _tiles_table(_scorecard(snapshot), st), Spacer(1, 14)]

    moves = snapshot.get("top_moves") or []
    if moves:
        story += _moves_section(moves, st)

    summary = snapshot.get("executive_summary")
    if summary:
        story += [Paragraph("THE SHORT VERSION", st["kicker"]),
                  Paragraph(_text(summary), st["body_lg"]), Spacer(1, 14)]

    charts = _charts(snapshot, st)
    if charts:
        story += [charts, Spacer(1, 14)]

    if findings and not moves:
        story += [CondPageBreak(1.6 * inch),
                  *_section("Fix these first", "Priorities", st),
                  _top_fixes(findings, st)]

    # Page 2: competitors and search ---------------------------------------
    story.append(PageBreak())
    story += _benchmark_section(snapshot, st)
    story += _snippet_section(snapshot, st)
    story += _gaps_section(snapshot, st)
    story += _ai_section(snapshot, st)
    story += _structure_section(snapshot, st)

    # Action plan --------------------------------------------------------
    if findings:
        story.append(CondPageBreak(3.2 * inch))
        story += [
            *_section("Your action plan", "Everything we found", st),
            Paragraph("In order of likely impact. Each item is explained, with how to fix it, "
                      "on the pages that follow.", st["muted"]),
            Spacer(1, 6),
            _action_plan(findings, st),
            Spacer(1, 18),
        ]
    if not snapshot.get("benchmarks"):
        story += _comparison_table(snapshot, st)
    story += _working(snapshot, st)

    # Details ------------------------------------------------------------
    if findings:
        story.append(PageBreak())
        story += _section("Details and how to fix each one", "The details", st)
        for i, f in enumerate(findings, start=1):
            story += [KeepTogether(_finding_card(i, f, st)), Spacer(1, 9)]

    step = _next_step(snapshot, st)
    if step:
        story += [Spacer(1, 6), KeepTogether(step)]
    note = snapshot.get("methodology_note")
    if note:
        story += [Spacer(1, 8), Paragraph(f"<b>About this audit.</b> {_text(note)}", st["small"])]

    doc.build(story)
    return buffer.getvalue()
