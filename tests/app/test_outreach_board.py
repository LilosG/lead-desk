from datetime import datetime, timedelta, timezone

from app.services.outreach_board import (
    OutreachBoardService,
    gmail_block_reason,
    next_step,
)


NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)


def ready_item(**changes):
    return {
        "channel": "email", "to_address": "a@b.co", "subject": "S", "body": "B",
        "verification_status": "not_required", "gmail_draft_id": None,
        "claim_signal": "audit_report",
        "gmail_draft_pending": False, "suppressed": False, **changes,
    }


def test_gmail_button_says_exactly_why_it_cannot_run():
    connected = {"gmail_connected": True}
    assert gmail_block_reason(ready_item(), **connected) is None
    assert "isn't connected" in gmail_block_reason(ready_item(), gmail_connected=False)
    assert "phone lead" in gmail_block_reason(ready_item(channel="phone"), **connected)
    assert "already exists" in gmail_block_reason(ready_item(gmail_draft_id="d"), **connected)
    assert "Generate draft" in gmail_block_reason(ready_item(body=None), **connected)
    assert "recipient" in gmail_block_reason(ready_item(to_address=" "), **connected)
    assert "do-not-contact" in gmail_block_reason(ready_item(suppressed=True), **connected)
    assert "verification" in gmail_block_reason(
        ready_item(verification_status="failed"), **connected)


def test_next_step_covers_every_stage_and_flags_follow_ups():
    assert "audit" in next_step({"stage": "to_prep"})
    assert "Generate" in next_step({"stage": "review", "has_draft": False})
    assert "Gmail" in next_step({"stage": "review", "has_draft": True})
    assert "send it from Gmail" in next_step({"stage": "in_gmail"})
    assert next_step({"stage": "contacted", "contacted_at": NOW - timedelta(days=2)}, NOW).startswith(
        "Waiting for a reply. Follow-up 1 on")
    assert next_step({"stage": "contacted", "contacted_at": NOW - timedelta(days=4)}, NOW) == "Follow-up 1 is due"
    assert next_step({"stage": "contacted", "follow_ups_drafted": 1, "follow_up_open": True,
                      "contacted_at": NOW}, NOW) == "Follow-up 1 is in Gmail. Review and send it"
    assert next_step({"stage": "contacted", "follow_ups_drafted": 2,
                      "contacted_at": NOW}, NOW) == "No reply after 3 emails. Call them or archive"


class FakeGmail:
    def __init__(self, live):
        self.live = live

    def list_draft_ids(self):
        return self.live


class FakeGmailRepo:
    def __init__(self, open_items):
        self.open_items = open_items
        self.moved = []

    def open_gmail_drafts(self, created_before):
        return self.open_items

    def mark_draft_left_gmail(self, item_id, draft_id):
        self.moved.append((item_id, draft_id))
        return True

    def open_follow_ups(self):
        return [{"id": "f1", "gmail_draft_id": "still-there"}, {"id": "f2", "gmail_draft_id": "gone-too"}]

    def mark_follow_up_left_gmail(self, follow_up_id):
        self.moved.append(follow_up_id)


def test_sync_moves_only_drafts_that_left_gmail():
    repo = FakeGmailRepo([
        {"id": "a", "gmail_draft_id": "still-there"},
        {"id": "b", "gmail_draft_id": "gone"},
    ])
    service = OutreachBoardService(None, gmail_repository=repo, gmail=FakeGmail({"still-there"}))
    assert service.sync_gmail() == {"checked": 2, "moved_to_contacted": 1}
    assert repo.moved == [("b", "gone"), "f2"]


def test_board_endpoint_returns_every_stage_count(client):
    body = client.get("/api/outreach/board").json()
    assert set(body["counts"]) == {
        "to_prep", "verify", "call", "review", "attention",
        "in_gmail", "contacted", "replied", "closed",
    }
    assert body["pagination"]["page"] == 1


def test_board_rejects_an_unknown_stage(client):
    assert client.get("/api/outreach/board?stage=nope").status_code == 422


def test_gmail_is_blocked_when_a_draft_has_no_audit_behind_it():
    item = ready_item(claim_signal="no_localbusiness_schema")
    assert "Regenerate draft" in gmail_block_reason(item, gmail_connected=True)
    assert gmail_block_reason(ready_item(claim_signal="audit_report"), gmail_connected=True) is None
