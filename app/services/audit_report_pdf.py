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
    }.get(status, (SURFACE_2, MUTED))


def _pill(label: str, status: str, style: ParagraphStyle) -> Table:
    bg, fg = _pill_colors(status)
    text_style = ParagraphStyle(
        f"Pill-{status}-{label}",
        parent=style,
        fontName="Helvetica-Bold",
        fontSize=7.2,
        leading=8.5,
        textColor=fg,
        alignment=TA_LEFT,
    )
    table = Table([[Paragraph(_text(label), text_style)]], colWidths=[None])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
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
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.52 * inch,
        bottomMargin=0.58 * inch,
        title=report["title"],
        author="LILOs Growth",
    )

    styles = getSampleStyleSheet()
    eyebrow = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=GOLD,
        spaceAfter=3,
    )
    title = ParagraphStyle(
        "AuditTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=27,
        textColor=WHITE,
        alignment=TA_LEFT,
        spaceAfter=3,
    )
    business_name = ParagraphStyle(
        "BusinessName",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        textColor=WHITE,
        spaceAfter=2,
    )
    hero_meta = ParagraphStyle(
        "HeroMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#d8d9d4"),
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14.5,
        leading=18,
        textColor=INK,
        spaceAfter=5,
    )
    section_kicker = ParagraphStyle(
        "SectionKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.4,
        leading=9,
        textColor=GOLD,
        spaceAfter=2,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.1,
        leading=13.2,
        textColor=INK,
        spaceAfter=4,
    )
    body_muted = ParagraphStyle(
        "BodyMuted",
        parent=body,
        fontSize=8.3,
        leading=11.5,
        textColor=MUTED,
    )
    label = ParagraphStyle(
        "Label",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=7.6,
        leading=9,
        textColor=MUTED,
        spaceAfter=2,
    )
    metric_value = ParagraphStyle(
        "MetricValue",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=INK,
        spaceAfter=1,
    )
    metric_label = ParagraphStyle(
        "MetricLabel",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=MUTED,
    )
    scope_title = ParagraphStyle(
        "ScopeTitle",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=8.1,
        leading=10,
        textColor=INK,
        spaceAfter=1,
    )
    scope_value = ParagraphStyle(
        "ScopeValue",
        parent=body,
        fontSize=7.7,
        leading=10.5,
        textColor=MUTED,
    )
    finding_title = ParagraphStyle(
        "FindingTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=INK,
        spaceAfter=1,
    )
    finding_number = ParagraphStyle(
        "FindingNumber",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=GOLD,
    )
    evidence_text = ParagraphStyle(
        "Evidence",
        parent=body,
        fontSize=8.2,
        leading=11.5,
        textColor=INK,
    )

    story = []

    location = business.get("location") or ""
    website = business.get("website_url") or ""
    checked = _pretty_date(snapshot.get("source_checked_at"))
    hero_meta_parts = [part for part in [location, website, f"Evidence date: {checked}"] if part]

    hero_left = [
        Paragraph("LILOS GROWTH / LOCAL SEARCH REVIEW", eyebrow),
        Paragraph("Local Visibility Audit", title),
        Paragraph(_text(business.get("name")), business_name),
        Paragraph(_text("   |   ".join(hero_meta_parts)), hero_meta),
    ]
    hero = Table([[hero_left]], colWidths=[7.4 * inch])
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ("TOPPADDING", (0, 0), (-1, -1), 16),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ]
        )
    )
    story.append(hero)
    story.append(Spacer(1, 12))

    metrics = []
    if business.get("rating") is not None:
        metrics.append((f"{float(business['rating']):.1f}", "Google rating"))
    if business.get("review_count") is not None:
        metrics.append((f"{int(business['review_count']):,}", "Google reviews"))
    metrics.append((str(len(findings)), "Selected findings"))
    if audit_scope:
        metrics.append((str(len(audit_scope)), "Checks represented"))

    metric_cells = []
    for value, name in metrics[:4]:
        metric_cells.append(
            [Paragraph(_text(value), metric_value), Paragraph(_text(name), metric_label)]
        )
    while len(metric_cells) < 4:
        metric_cells.append([Paragraph("-", metric_value), Paragraph("Context", metric_label)])

    metric_table = Table(
        [[cell for cell in metric_cells]],
        colWidths=[1.78 * inch] * 4,
    )
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(metric_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("EXECUTIVE READOUT", section_kicker))
    story.append(Paragraph("What stood out", section))
    summary_text = snapshot.get("executive_summary") or (
        f"This report summarizes {len(findings)} selected observations from the available public business and website evidence."
    )
    summary_box = Table([[Paragraph(_text(summary_text), body)]], colWidths=[7.1 * inch])
    summary_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("LINEBEFORE", (0, 0), (0, -1), 4, GOLD),
                ("LEFTPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 13),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(summary_box)
    story.append(Spacer(1, 14))

    if audit_scope:
        story.append(Paragraph("AUDIT COVERAGE", section_kicker))
        story.append(Paragraph("What we checked", section))
        story.append(
            Paragraph(
                "The selected findings below are the items presented for action. This section shows the broader client-safe evidence reviewed in the same snapshot.",
                body_muted,
            )
        )
        story.append(Spacer(1, 5))

        scope_cells = []
        for item in audit_scope:
            status_labels = {
                "confirmed": "Confirmed",
                "attention": "Attention",
                "review": "Verify",
                "context": "Context",
            }
            cell = [
                Paragraph(_text(item.get("label")), scope_title),
                Paragraph(_text(item.get("value")), scope_value),
                Spacer(1, 3),
                _pill(status_labels.get(item.get("status"), "Reviewed"), item.get("status", "context"), label),
            ]
            scope_cells.append(cell)

        rows = []
        for i in range(0, len(scope_cells), 2):
            row = [scope_cells[i]]
            row.append(scope_cells[i + 1] if i + 1 < len(scope_cells) else [])
            rows.append(row)

        scope_table = Table(rows, colWidths=[3.53 * inch, 3.53 * inch])
        scope_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(scope_table)

    story.append(PageBreak())
    story.append(Paragraph("SELECTED FINDINGS", section_kicker))
    story.append(Paragraph("Issues worth reviewing", section))
    story.append(
        Paragraph(
            "Each item below is tied to an observed condition from the audit snapshot. Recommendations are intentionally practical and client-safe rather than a dump of internal scoring or implementation logic.",
            body_muted,
        )
    )
    story.append(Spacer(1, 9))

    disposition_labels = {
        "recommended": "Recommended",
        "optional": "Opportunity",
        "review_required": "Verify first",
    }

    for index, finding in enumerate(findings, start=1):
        disposition = finding.get("disposition") or "optional"
        heading = Table(
            [[
                [
                    Paragraph(f"FINDING {index:02d}", finding_number),
                    Paragraph(_text(finding.get("title")), finding_title),
                    Paragraph(_text(finding.get("category")), body_muted),
                ],
                _pill(disposition_labels.get(disposition, "Review"), disposition, label),
            ]],
            colWidths=[5.85 * inch, 1.15 * inch],
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
            [Paragraph("WHAT WE OBSERVED", label), Paragraph(_text(finding.get("what_we_found")), body)],
        ]
        if finding.get("evidence"):
            detail_rows.append(
                [
                    Paragraph("EVIDENCE", label),
                    Paragraph(_text(finding.get("evidence")), evidence_text),
                ]
            )
        detail_rows.extend(
            [
                [Paragraph("WHY IT MATTERS", label), Paragraph(_text(finding.get("why_it_matters")), body)],
                [Paragraph("RECOMMENDED ACTION", label), Paragraph(_text(finding.get("recommendation")), body)],
            ]
        )

        detail_table = Table(detail_rows, colWidths=[1.35 * inch, 5.55 * inch])
        detail_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEABOVE", (0, 1), (-1, -1), 0.35, LINE),
                    ("LEFTPADDING", (0, 0), (0, -1), 0),
                    ("RIGHTPADDING", (0, 0), (0, -1), 10),
                    ("LEFTPADDING", (1, 0), (1, -1), 0),
                    ("RIGHTPADDING", (1, 0), (1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )

        card = Table([[heading], [detail_table]], colWidths=[7.1 * inch])
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                    ("LINEBEFORE", (0, 0), (0, -1), 4, GOLD),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, 0), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 1), (-1, 1), 0),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                ]
            )
        )
        story.append(KeepTogether(card))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 5))
    story.append(Paragraph("NEXT STEP", section_kicker))
    story.append(Paragraph("Use this as a review checklist", section))
    closing = (
        "The findings above are designed to be verified and prioritized, not treated as a generic scorecard. "
        "If a change is already intentional or has been corrected since the evidence date, it should be rechecked before implementation."
    )
    closing_box = Table([[Paragraph(closing, body)]], colWidths=[7.1 * inch])
    closing_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(closing_box)
    story.append(Spacer(1, 10))
    story.append(Paragraph("ABOUT THIS AUDIT", section_kicker))
    story.append(Paragraph(_text(snapshot.get("methodology_note")), body_muted))
    story.append(Spacer(1, 5))
    story.append(
        Paragraph(
            "Prepared by LILOs Growth  |  1440 Columbia St, San Diego, CA 92101",
            body_muted,
        )
    )

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(0.55 * inch, 0.42 * inch, 7.95 * inch, 0.42 * inch)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.55 * inch, 0.25 * inch, "LILOs Growth  |  Local Visibility Audit")
        canvas.drawRightString(7.95 * inch, 0.25 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
