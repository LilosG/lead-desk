from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


INK = colors.HexColor("#23231f")
MUTED = colors.HexColor("#6f716a")
LINE = colors.HexColor("#deddd7")
SURFACE = colors.HexColor("#f4f2ed")
ACCENT = colors.HexColor("#dfeee5")


def _text(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_audit_report_pdf(report: dict) -> bytes:
    snapshot = report["snapshot"]
    business = snapshot["business"]
    findings = snapshot["findings"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.58 * inch,
        title=report["title"],
        author="LILOs Growth",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "AuditTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    eyebrow = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        tracking=1.4,
        textColor=MUTED,
        spaceAfter=7,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=INK,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=INK,
        spaceAfter=5,
    )
    small = ParagraphStyle(
        "Small",
        parent=body,
        fontSize=8,
        leading=11,
        textColor=MUTED,
    )
    label = ParagraphStyle(
        "Label",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=MUTED,
        spaceAfter=2,
    )

    story = []
    story.append(Paragraph("LILOS GROWTH", eyebrow))
    story.append(Paragraph("Local Visibility Audit", title))
    story.append(Paragraph(_text(business.get("name")), h2))
    if business.get("location"):
        story.append(Paragraph(_text(business["location"]), small))
    story.append(Spacer(1, 12))

    summary_cells = []
    if business.get("rating") is not None:
        summary_cells.append([
            Paragraph("Google rating", label),
            Paragraph(_text(business.get("rating")), body),
        ])
    if business.get("review_count") is not None:
        summary_cells.append([
            Paragraph("Google reviews", label),
            Paragraph(f"{int(business['review_count']):,}", body),
        ])
    if snapshot.get("source_checked_at"):
        summary_cells.append([
            Paragraph("Evidence checked", label),
            Paragraph(_text(snapshot.get("source_checked_at")), small),
        ])

    if summary_cells:
        summary_table = Table(summary_cells, colWidths=[1.55 * inch, 4.95 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 16))

    story.append(Paragraph("Executive summary", h2))
    intro = (
        f"We reviewed the public business information and website signals currently available for "
        f"{_text(business.get('name'))}. This report highlights {len(findings)} selected observations "
        "that are specific to the business and useful to review as part of its local search presence."
    )
    story.append(Paragraph(intro, body))
    story.append(Spacer(1, 8))

    for index, finding in enumerate(findings, start=1):
        evidence = finding.get("evidence")
        blocks = [
            Paragraph(f"{index}. {_text(finding['title'])}", h2),
            Paragraph(_text(finding.get("category")), eyebrow),
            Paragraph("What we found", label),
            Paragraph(_text(finding.get("what_we_found")), body),
        ]
        if evidence:
            blocks.extend([
                Paragraph("Observed evidence", label),
                Paragraph(_text(evidence), small),
            ])
        blocks.extend([
            Paragraph("Why it matters", label),
            Paragraph(_text(finding.get("why_it_matters")), body),
            Paragraph("Recommended next step", label),
            Paragraph(_text(finding.get("recommendation")), body),
        ])
        card = Table([[blocks]], colWidths=[6.5 * inch])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.65, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 11),
            ("RIGHTPADDING", (0, 0), (-1, -1), 11),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.append(KeepTogether(card))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 6))
    story.append(Paragraph("About this audit", h2))
    story.append(Paragraph(_text(snapshot.get("methodology_note")), small))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Prepared by LILOs Growth · 1440 Columbia St · San Diego, CA 92101", small))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(0.62 * inch, 0.43 * inch, 7.88 * inch, 0.43 * inch)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.62 * inch, 0.27 * inch, "LILOs Growth · Local Visibility Audit")
        canvas.drawRightString(7.88 * inch, 0.27 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
