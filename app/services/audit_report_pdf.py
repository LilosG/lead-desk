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


def _status_text(status: str) -> str:
    return {
        "confirmed": "Confirmed",
        "attention": "Attention",
        "review": "Verify",
        "context": "Context",
        "recommended": "Recommended",
        "optional": "Opportunity",
        "review_required": "Verify first",
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
        fontSize=11.2,
        leading=13.2,
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
        fontSize=7.4,
        leading=9.6,
        textColor=INK,
    )

    story = []
    checked = _pretty_date(snapshot.get("source_checked_at"))
    location = business.get("location") or ""
    website = business.get("website_url") or ""
    hero_meta_parts = [part for part in [location, website, f"Evidence date: {checked}"] if part]

    hero = Table(
        [[[
            Paragraph("LILOS GROWTH / LOCAL SEARCH REVIEW", eyebrow),
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
    metrics.append((str(len(findings)), "Selected findings"))
    metrics.append((str(len(audit_scope)), "Checks reviewed"))
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

    story.append(Paragraph("EXECUTIVE READOUT", section_kicker))
    story.append(Paragraph("What stood out", section))
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

    if audit_scope:
        story.append(Paragraph("AUDIT COVERAGE", section_kicker))
        story.append(Paragraph("What we checked", section))
        story.append(
            Paragraph(
                "These client-safe checks show the broader evidence reviewed; selected findings are detailed on page 2.",
                body_muted,
            )
        )
        story.append(Spacer(1, 3))

        scope_cells = []
        for item in audit_scope:
            status = item.get("status") or "context"
            left = [
                Paragraph(_text(item.get("label")), scope_title),
                Paragraph(_text(item.get("value")), scope_value),
            ]
            cell = Table(
                [[left, _status_badge(_status_text(status), status, label)]],
                colWidths=[2.58 * inch, 0.78 * inch],
            )
            cell.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            scope_cells.append(cell)

        rows = []
        for i in range(0, len(scope_cells), 2):
            rows.append([
                scope_cells[i],
                scope_cells[i + 1] if i + 1 < len(scope_cells) else "",
            ])

        scope_table = Table(rows, colWidths=[3.62 * inch, 3.62 * inch])
        scope_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.45, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(scope_table)

    story.append(PageBreak())
    story.append(Paragraph("SELECTED FINDINGS", section_kicker))
    story.append(Paragraph("Issues worth reviewing", section))
    story.append(
        Paragraph(
            "Each item below is tied to an observed condition from the same audit snapshot.",
            body_muted,
        )
    )
    story.append(Spacer(1, 5))

    for index, finding in enumerate(findings, start=1):
        disposition = finding.get("disposition") or "optional"
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
            [Paragraph("WHAT WE OBSERVED", label), Paragraph(_text(finding.get("what_we_found")), body)],
        ]
        if finding.get("evidence"):
            detail_rows.append([Paragraph("EVIDENCE", label), Paragraph(_text(finding.get("evidence")), evidence_text)])
        detail_rows.extend(
            [
                [Paragraph("WHY IT MATTERS", label), Paragraph(_text(finding.get("why_it_matters")), body)],
                [Paragraph("RECOMMENDED ACTION", label), Paragraph(_text(finding.get("recommendation")), body)],
            ]
        )
        detail_table = Table(detail_rows, colWidths=[1.28 * inch, 5.65 * inch])
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
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, 0), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                    ("TOPPADDING", (0, 1), (-1, 1), 0),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
                ]
            )
        )
        story.append(KeepTogether(card))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 2))
    story.append(Paragraph("NEXT STEP", section_kicker))
    story.append(Paragraph("Use this as a review checklist", section))
    closing = (
        "These findings are intended to be verified and prioritized. If an item is intentional or has changed since the evidence date, recheck it before implementation."
    )
    closing_box = Table([[Paragraph(closing, body)]], colWidths=[7.28 * inch])
    closing_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(closing_box)
    story.append(Spacer(1, 5))
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
