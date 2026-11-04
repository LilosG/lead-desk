from app.services.outreach import OutreachBlocked, OutreachIntegrationUnavailable
from app.services.outreach_bulk import bulk_set_status, fast_track


class FakeRepo:
    def __init__(self, items):
        self.items = items

    def get_item(self, item_id):
        item = self.items.get(item_id)
        return dict(item) if item else None

    def find_email_item(self, place_id, campaign_key):
        return next((dict(i) for i in self.items.values() if i["place_id"] == place_id), None)


class FakeOutreach:
    def __init__(self, gmail_error=None):
        self.repository = FakeRepo({})
        self.calls = []
        self.gmail_error = gmail_error

    def _save(self, item):
        self.repository.items[item["id"]] = item
        return dict(item)

    def cooldown_block(self, place_id, campaign_key):
        return None

    def create_item(self, place_id, channel, to_address, campaign_key):
        self.calls.append("queue")
        existing = self.repository.items.get("q1")
        return dict(existing) if existing else self._save(
            {"id": "q1", "place_id": place_id, "status": "queued", "version": 1, "body": None})

    def generate_draft(self, item_id, *, expected_version):
        self.calls.append("draft")
        item = self.repository.items[item_id]
        return self._save({**item, "status": "review_required", "body": "Hi", "subject": "S",
                           "version": item["version"] + 1})

    def update_item(self, item_id, *, changes, expected_version):
        item = self.repository.items[item_id]
        assert item["version"] == expected_version
        self.calls.append(f"status:{changes['status']}")
        return self._save({**item, **changes, "version": item["version"] + 1})

    def create_gmail_draft(self, item_id, *, expected_version):
        if self.gmail_error:
            raise OutreachIntegrationUnavailable(self.gmail_error)
        self.calls.append("gmail")
        item = self.repository.items[item_id]
        return self._save({**item, "gmail_draft_id": "d1", "version": item["version"] + 1})


class FakeAudits:
    def __init__(self, status="created"):
        self.status = status

    def create_default_reports(self, place_ids):
        return [{"place_id": place_ids[0], "status": self.status, "report_id": "r1",
                 "detail": None if self.status == "created" else "no default findings to report"}]


def test_fast_track_runs_every_step_to_a_gmail_draft():
    outreach = FakeOutreach()
    result = fast_track(outreach, FakeAudits(), "p1")
    assert result["ok"] is True
    assert result["steps"] == ["audit", "queue", "draft", "ready", "gmail_draft"]
    assert outreach.calls == ["queue", "draft", "status:draft_ready", "gmail"]


def test_fast_track_stops_and_says_which_step_failed():
    outreach = FakeOutreach(gmail_error="Gmail access has expired")
    result = fast_track(outreach, FakeAudits(), "p1")
    assert result["ok"] is False
    assert result["failed_step"] == "gmail_draft"
    assert "expired" in result["detail"]
    assert result["steps"] == ["audit", "queue", "draft", "ready"]


def test_fast_track_skips_prospects_with_nothing_to_audit():
    result = fast_track(FakeOutreach(), FakeAudits(status="skipped"), "p1")
    assert result["ok"] is False and result["failed_step"] == "audit"


def test_fast_track_does_not_duplicate_an_existing_gmail_draft():
    outreach = FakeOutreach()
    outreach.repository.items["q1"] = {"id": "q1", "place_id": "p1", "status": "draft_ready",
                                       "version": 3, "body": "Hi", "gmail_draft_id": "d0"}
    result = fast_track(outreach, FakeAudits(), "p1")
    assert result["ok"] is True
    assert "gmail" not in outreach.calls


def test_fast_track_resumes_without_replacing_an_existing_draft():
    outreach = FakeOutreach()
    outreach.repository.items["q1"] = {"id": "q1", "place_id": "p1", "status": "review_required",
                                       "version": 3, "body": "Edited by hand", "gmail_draft_id": None,
                                       "claim_signal": "audit_report"}
    audits = FakeAudits()
    result = fast_track(outreach, audits, "p1")
    assert result["ok"] is True
    assert "draft" not in outreach.calls and "gmail" in outreach.calls
    assert outreach.repository.items["q1"]["body"] == "Edited by hand"


def test_bulk_status_updates_each_item_and_reports_failures():
    outreach = FakeOutreach()
    outreach.repository.items = {
        "a": {"id": "a", "status": "draft_ready", "version": 1},
        "b": {"id": "b", "status": "contacted", "version": 4},
    }

    def blocked_for_c(item_id, *, changes, expected_version):
        raise OutreachBlocked("email address is suppressed")

    results = bulk_set_status(outreach, ["a", "b", "missing"], "contacted")
    by_id = {r["id"]: r for r in results}
    assert by_id["a"]["ok"] is True and outreach.repository.items["a"]["status"] == "contacted"
    assert by_id["b"]["detail"] == "already set"
    assert by_id["missing"]["ok"] is False

    outreach.repository.items["c"] = {"id": "c", "status": "draft_ready", "version": 1}
    outreach.update_item = blocked_for_c
    assert bulk_set_status(outreach, ["c"], "contacted")[0]["detail"] == "email address is suppressed"
