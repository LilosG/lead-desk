from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


INK = colors.HexColor("#1f211d")
MUTED = colors.HexColor("#6f7169")
LINE = colors.HexColor("#dedbd2")
SURFACE = colors.HexColor("#f5f3ee")
SURFACE_2 = colors.HexColor("#eeebe4")
DARK = colors.HexColor("#272923")
GOLD = colors.HexColor("#b59a61")
GREEN_BG = colors.HexColor("#e7f3eb")
GREEN_FG = colors.HexColor("#256645")
AMBER_BG = colors.HexColor("#f6ecd6")
AMBER_FG = colors.HexColor("#8a641f")
BLUE_BG = colors.HexColor("#eaf0f7")
BLUE_FG = colors.HexColor("#355a7a")
RED_BG = colors.HexColor("#f6e4e1")
RED_FG = colors.HexColor("#8a3c32")
WHITE = colors.white


def _text(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _pretty_date(value: object) -> str:
    if not value:
        return "Not available"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return raw


def _pill_colors(status: str) -> tuple[colors.Color, colors.Color]:
    return {
        "confirmed": (GREEN_BG, GREEN_FG),
        "attention": (AMBER_BG, AMBER_FG),
        "review": (RED_BG, RED_FG),
        "context": (BLUE_BG, BLUE_FG),
        "recommended": (AMBER_BG, AMBER_FG),
        "optional": (BLUE_BG, BLUE_FG),
        "review_required": (RED_BG, RED_FG),
        "high": (RED_BG, RED_FG),
        "medium": (AMBER_BG, AMBER_FG),
        "low": (GREEN_BG, GREEN_FG),
    }.get(status, (SURFACE_2, MUTED))


def _status_text(status: str) -> str:
    return {
        "confirmed": "Confirmed",
        "attention": "Attention",
        "review": "Verify",
        "context": "Context",
        "recommended": "Priority",
        "optional": "Supporting",
        "review_required": "Verify first",
        "high": "High impact",
        "medium": "Medium impact",
        "low": "Quick win",
    }.get(status, "Reviewed")


def _status_badge(label: str, status: str, parent: ParagraphStyle) -> Table:
    bg, fg = _pill_colors(status)
    style = ParagraphStyle(
        f"Badge-{status}-{label}",
        parent=parent,
        fontName="Helvetica-Bold",
        fontSize=6.6,
        leading=7.5,
        textColor=fg,
        alignment=TA_LEFT,
    )
    table = Table([[Paragraph(_text(label), style)]])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def render_audit_report_pdf(report: dict) -> bytes:
    snapshot = report["snapshot"]
    business = snapshot["business"]
    findings = snapshot.get("findings") or []
    audit_scope = snapshot.get("audit_scope") or []

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.48 * inch,
        leftMargin=0.48 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.48 * inch,
        title=report["title"],
        author="LILOs Growth",
    )

    styles = getSampleStyleSheet()
    eyebrow = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.8,
        leading=8,
        textColor=GOLD,
        spaceAfter=2,
    )
    title = ParagraphStyle(
        "AuditTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20.5,
        leading=22.5,
        textColor=WHITE,
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    business_name = ParagraphStyle(
        "BusinessName",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=13.5,
        textColor=WHITE,
        spaceAfter=1,
    )
    hero_meta = ParagraphStyle(
        "HeroMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.3,
        leading=9,
        textColor=colors.HexColor("#d8d9d4"),
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12.2,
        leading=14.5,
        textColor=INK,
        spaceAfter=3,
    )
    section_kicker = ParagraphStyle(
        "SectionKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.6,
        leading=8,
        textColor=GOLD,
        spaceAfter=1,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.1,
        leading=10.7,
        textColor=INK,
        spaceAfter=2,
    )
    body_muted = ParagraphStyle(
        "BodyMuted",
        parent=body,
        fontSize=7.4,
        leading=9.5,
        textColor=MUTED,
    )
    label = ParagraphStyle(
        "Label",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=6.7,
        leading=8,
        textColor=MUTED,
    )
    metric_value = ParagraphStyle(
        "MetricValue",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=15.5,
        leading=17,
        textColor=INK,
        spaceAfter=0,
    )
    metric_label = ParagraphStyle(
        "MetricLabel",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=6.7,
        leading=8,
        textColor=MUTED,
    )
    scope_title = ParagraphStyle(
        "ScopeTitle",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=7.2,
        leading=8.5,
        textColor=INK,
    )
    scope_value = ParagraphStyle(
        "ScopeValue",
        parent=body,
        fontSize=6.8,
        leading=8.2,
        textColor=MUTED,
    )
    finding_title = ParagraphStyle(
        "FindingTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.2,
        leading=11.8,
        textColor=INK,
        spaceAfter=0,
    )
    finding_number = ParagraphStyle(
        "FindingNumber",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        textColor=GOLD,
    )
    evidence_text = ParagraphStyle(
        "Evidence",
        parent=body,
        fontSize=6.9,
        leading=8.2,
        textColor=INK,
    )

    finding_body = ParagraphStyle(
        "FindingBody",
        parent=body,
        fontSize=7.2,
        leading=8.6,
        spaceAfter=0,
    )

    finding_label = ParagraphStyle(
        "FindingLabel",
        parent=label,
        fontSize=6.2,
        leading=7.2,
        spaceAfter=0,
    )

    story = []
    checked = _pretty_date(snapshot.get("source_checked_at"))
    location = business.get("location") or ""
    website = business.get("website_url") or ""
    hero_meta_parts = [part for part in [location, website, f"Evidence date: {checked}"] if part]

    hero = Table(
        [[[
            Paragraph("LILOS GROWTH / LOCAL VISIBILITY REVIEW", eyebrow),
            Paragraph("Local Visibility Audit", title),
            Paragraph(_text(business.get("name")), business_name),
            Paragraph(_text("  |  ".join(hero_meta_parts)), hero_meta),
        ]]],
        colWidths=[7.54 * inch],
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
            ]
        )
    )
    story.append(hero)
    story.append(Spacer(1, 7))

    metrics = []
    if business.get("rating") is not None:
        metrics.append((f"{float(business['rating']):.1f}", "Google rating"))
    if business.get("review_count") is not None:
        metrics.append((f"{int(business['review_count']):,}", "Google reviews"))
    metrics.append((str(len(findings)), "Items to improve"))
    high = sum(1 for f in findings if f.get("impact") == "high")
    if high:
        metrics.append((str(high), "High impact"))
    else:
        metrics.append((str(sum(1 for f in findings if f.get("impact") == "medium")), "Medium impact"))
    cells = [[Paragraph(_text(v), metric_value), Paragraph(_text(k), metric_label)] for v, k in metrics[:4]]
    metric_table = Table([[cell for cell in cells]], colWidths=[1.82 * inch] * 4)
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.45, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(metric_table)
    story.append(Spacer(1, 7))

    story.append(Paragraph("SUMMARY", section_kicker))
    story.append(Paragraph("What we found", section))
    summary_text = snapshot.get("executive_summary") or (
        f"We reviewed the available public business and website evidence and selected {len(findings)} items for follow-up."
    )
    summary_box = Table([[Paragraph(_text(summary_text), body)]], colWidths=[7.28 * inch])
    summary_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(summary_box)
    story.append(Spacer(1, 7))

    comparison = snapshot.get("market_comparison")
    if comparison:
        story.append(Paragraph("LOCAL COMPARISON", section_kicker))
        story.append(
            Paragraph(
                _text(f"How {business.get('name') or 'the business'} compares in {comparison.get('market')}"),
                section,
            )
        )
        story.append(
            Paragraph(
                _text(
                    f"Public Google data for {comparison.get('sample_size')} comparable "
                    f"{comparison.get('niche')} businesses in {comparison.get('market')}. "
                    f"Typical (median) review count: {comparison.get('median_reviews')}. "
                    f"The three with the most reviews are shown for reference."
                ),
                body_muted,
            )
        )
        story.append(Spacer(1, 3))

        def _row(item: dict, highlight: bool) -> list:
            rating = item.get("rating")
            return [
                Paragraph(_text(item.get("name")) + (" (you)" if highlight else ""), scope_title),
                Paragraph(_text(f"{float(rating):.1f}" if rating is not None else "—"), scope_value),
                Paragraph(_text(f"{int(item.get('review_count') or 0):,}"), scope_value),
                Paragraph("Yes" if item.get("has_website") else "No", scope_value),
            ]

        header = [
            Paragraph("BUSINESS", label),
            Paragraph("RATING", label),
            Paragraph("REVIEWS", label),
            Paragraph("WEBSITE", label),
        ]
        rows = [header, _row(comparison.get("business") or {}, True)]
        rows += [_row(item, False) for item in comparison.get("leaders") or []]
        comp_table = Table(rows, colWidths=[4.0 * inch, 1.0 * inch, 1.14 * inch, 1.14 * inch])
        comp_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.45, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                    ("BACKGROUND", (0, 0), (-1, 0), SURFACE_2),
                    ("BACKGROUND", (0, 1), (-1, 1), SURFACE),
                    ("LINEBEFORE", (0, 1), (0, 1), 3, GOLD),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(KeepTogether(comp_table))
        story.append(Spacer(1, 7))

    if findings:
        story.append(Paragraph("PRIORITIES", section_kicker))
        story.append(Paragraph("What to fix, in order", section))
        story.append(
            Paragraph(
                "Ordered by likely impact. Each item is explained in detail on the following page.",
                body_muted,
            )
        )
        story.append(Spacer(1, 3))

        opportunity_rows = []
        for finding in findings:
            disposition = finding.get("impact") or finding.get("disposition") or "optional"
            opportunity_rows.append(
                [
                    Paragraph(_text(finding.get("title")), scope_title),
                    Paragraph(_text(finding.get("what_we_found")), scope_value),
                    _status_badge(_status_text(disposition), disposition, label),
                ]
            )

        opportunity_table = Table(
            opportunity_rows,
            colWidths=[1.78 * inch, 4.42 * inch, 1.08 * inch],
        )
        opportunity_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.45, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(opportunity_table)
        story.append(Spacer(1, 7))

    confirmed = [
        item for item in audit_scope
        if item.get("status") == "confirmed"
    ]
    if confirmed:
        story.append(Paragraph("CONFIRMED BASELINE", section_kicker))
        story.append(Paragraph("What is already in place", section))

        strength_rows = []
        strength_cells = [
            [
                Paragraph(_text(item.get("label")), scope_title),
                Paragraph(_text(item.get("value")), scope_value),
            ]
            for item in confirmed
        ]

        for i in range(0, len(strength_cells), 2):
            strength_rows.append(
                [
                    strength_cells[i],
                    strength_cells[i + 1] if i + 1 < len(strength_cells) else "",
                ]
            )

        strength_table = Table(
            strength_rows,
            colWidths=[3.62 * inch, 3.62 * inch],
        )
        strength_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.45, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                    ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(strength_table)

    story.append(PageBreak())
    story.append(Paragraph("OPPORTUNITIES", section_kicker))
    story.append(Paragraph("Details and how to fix each one", section))
    story.append(
        Paragraph(
            "Each item is based on what we observed on the Google profile and website on the date shown.",
            body_muted,
        )
    )
    story.append(Spacer(1, 5))

    for index, finding in enumerate(findings, start=1):
        disposition = finding.get("impact") or finding.get("disposition") or "optional"
        heading = Table(
            [[[
                Paragraph(f"FINDING {index:02d}", finding_number),
                Paragraph(_text(finding.get("title")), finding_title),
                Paragraph(_text(finding.get("category")), body_muted),
            ], _status_badge(_status_text(disposition), disposition, label)]],
            colWidths=[6.02 * inch, 1.08 * inch],
        )
        heading.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        detail_rows = [
            [Paragraph("WHAT WE FOUND", finding_label), Paragraph(_text(finding.get("what_we_found")), finding_body)],
        ]
        if finding.get("evidence"):
            detail_rows.append([Paragraph("EVIDENCE", finding_label), Paragraph(_text(finding.get("evidence")), evidence_text)])
        detail_rows.extend(
            [
                [Paragraph("WHY IT MATTERS", finding_label), Paragraph(_text(finding.get("why_it_matters")), finding_body)],
                [Paragraph("HOW TO FIX IT", finding_label), Paragraph(_text(finding.get("recommendation")), finding_body)],
            ]
        )
        detail_table = Table(detail_rows, colWidths=[1.12 * inch, 5.81 * inch])
        detail_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEABOVE", (0, 1), (-1, -1), 0.3, LINE),
                    ("LEFTPADDING", (0, 0), (0, -1), 0),
                    ("RIGHTPADDING", (0, 0), (0, -1), 8),
                    ("LEFTPADDING", (1, 0), (1, -1), 0),
                    ("RIGHTPADDING", (1, 0), (1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        card = Table([[heading], [detail_table]], colWidths=[7.28 * inch])
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                    ("TOPPADDING", (0, 1), (-1, 1), 0),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
                ]
            )
        )
        story.append(KeepTogether(card))
        story.append(Spacer(1, 3))

    step = snapshot.get("next_step")
    if step and step.get("text"):
        story.append(Spacer(1, 4))
        step_parts = [Paragraph("NEXT STEP", section_kicker), Paragraph(_text(step["text"]), body)]
        if step.get("demo_url"):
            url = _text(step["demo_url"])
            step_parts.append(
                Paragraph(f'Concept homepage: <link href="{url}" color="#355a7a">{url}</link>', body)
            )
        step_box = Table([[step_parts]], colWidths=[7.28 * inch])
        step_box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(KeepTogether(step_box))

    story.append(Spacer(1, 4))
    story.append(Spacer(1, 3))

    methodology = _text(snapshot.get("methodology_note"))
    story.append(
        Paragraph(
            f"<b>About this audit:</b> {methodology} &nbsp;&nbsp; Prepared by LILOs Growth | 1440 Columbia St, San Diego, CA 92101",
            body_muted,
        )
    )

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(0.48 * inch, 0.36 * inch, 8.02 * inch, 0.36 * inch)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.48 * inch, 0.22 * inch, "LILOs Growth  |  Local Visibility Audit")
        canvas.drawRightString(8.02 * inch, 0.22 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
