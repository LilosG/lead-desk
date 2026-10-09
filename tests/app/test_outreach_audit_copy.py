import base64
import email

from app.integrations.gmail import GmailDraftClient
from app.services.outreach import OutreachService
from app.services.outreach_audit_copy import audit_email_paragraph, clean_business_name


def test_keyword_stuffed_google_names_are_cleaned():
    assert clean_business_name("Waterfront Plumbing | 24/7 Emergency Plumbers in Vista") == "Waterfront Plumbing"
    assert clean_business_name("Ascend Plumbing - San Diego CA") == "Ascend Plumbing"
    assert clean_business_name("Smith Electrical Contractors, Inc.") == "Smith Electrical Contractors"
    assert clean_business_name("Repipe & Water Heaters 4 Less Inc. | San Diego") == "Repipe & Water Heaters 4 Less"
    assert clean_business_name("1st Choice Plumbing, Flood & Restoration") == "1st Choice Plumbing, Flood & Restoration"


def test_broken_profile_link_leads_and_sets_subject():
    snapshot = {"findings": [
        {"signal": "no_localbusiness_schema", "phrase": "x"},
        {"signal": "broken_profile_link", "phrase": "the website link on the Google profile"},
    ]}
    paragraph, subject = audit_email_paragraph(snapshot, "Aesthetic Assets")
    assert paragraph.startswith("The website link on Aesthetic Assets' Google listing opens an error page")
    assert "The homepage itself loads fine" in paragraph
    assert subject == "Aesthetic Assets website link on Google"


def test_single_review_count_gets_no_misleading_praise():
    snapshot = {
        "business": {"rating": 5.0, "review_count": 1},
        "market_comparison": {"market": "Scottsdale, AZ", "niche": "med spa", "median_reviews": 66},
        "findings": [{"signal": "reviews_bottom_quartile",
                      "data": {"reviews": 1, "median": 66, "market": "Scottsdale, AZ", "niche": "med spa"}}],
    }
    paragraph, _ = audit_email_paragraph(snapshot, "NMD Scottsdale Med Spa")
    assert "has 1 Google review;" in paragraph
    assert "the typical med spa in Scottsdale has about 66" in paragraph
    assert "excellent" not in paragraph and "great" not in paragraph


def test_gmail_message_carries_pdf_attachment():
    client = GmailDraftClient.__new__(GmailDraftClient)
    client.sender_email = "mike@lilosgrowth.com"
    raw = client._raw_message(
        to_address="owner@example.com", subject="Test", body="Body",
        attachments=[("Glow - Local Visibility Audit.pdf", b"%PDF-1.4 test")],
    )
    message = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    parts = [p for p in message.walk() if p.get_filename()]
    assert parts and parts[0].get_filename() == "Glow - Local Visibility Audit.pdf"
    assert parts[0].get_content_type() == "application/pdf"


class _Repo:
    def latest_audit_report(self, place_id):
        return {"id": "r1", "title": "Local Visibility Audit", "name": "Glow Med Spa | Scottsdale",
                "snapshot": {"business": {"name": "Glow Med Spa"}, "findings": [], "audit_scope": []}}


def test_audit_grounded_drafts_attach_the_report_and_others_do_not():
    service = OutreachService(_Repo())
    attached = service.audit_attachments({"claim_signal": "audit_report", "place_id": "p1"})
    assert attached and attached[0][0] == "Glow Med Spa - Local Visibility Audit.pdf"
    assert attached[0][1].startswith(b"%PDF")
    assert service.audit_attachments({"claim_signal": "no_ssl", "place_id": "p1"}) is None
