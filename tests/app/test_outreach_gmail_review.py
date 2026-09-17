from app.integrations.gmail import GmailDraftClient, GmailDraftError, GmailDraftResult
from app.services.outreach_gmail_review import OutreachGmailReviewService


class _Repository:
    def __init__(self, item):
        self.item = dict(item)

    def get_item(self, item_id):
        assert item_id == self.item["id"]
        return dict(self.item)


class _GmailRepository:
    def __init__(self, repository):
        self.repository = repository
        self.cleared = False

    def clear_stale_draft(self, item_id, *, expected_version, stale_draft_id):
        assert expected_version == self.repository.item["version"]
        assert stale_draft_id == self.repository.item["gmail_draft_id"]
        self.cleared = True
        self.repository.item.update({
            "gmail_draft_id": None,
            "gmail_message_id": None,
            "gmail_draft_created_at": None,
            "version": expected_version + 1,
        })
        return dict(self.repository.item), False


class _Gmail:
    def __init__(self, remote):
        self.remote = remote
        self.checked = []

    def get_draft(self, draft_id):
        self.checked.append(draft_id)
        return self.remote


class _Outreach:
    def __init__(self, repository):
        self.repository = repository
        self.updated = None
        self.created = None

    def update_item(self, item_id, *, changes, expected_version):
        self.updated = {"item_id": item_id, "changes": changes, "expected_version": expected_version}
        self.repository.item.update(changes)
        self.repository.item["version"] = expected_version + 1
        return dict(self.repository.item)

    def create_gmail_draft(self, item_id, *, expected_version):
        self.created = {"item_id": item_id, "expected_version": expected_version}
        self.repository.item.update({
            "gmail_draft_id": "new-draft",
            "version": expected_version + 1,
        })
        return dict(self.repository.item)


def _item(**overrides):
    item = {
        "id": "11111111-1111-1111-1111-111111111111",
        "channel": "email",
        "status": "review_required",
        "to_address": "owner@example.com",
        "subject": "Example Electric",
        "body": "Reviewed body",
        "verification_status": "verified",
        "gmail_draft_id": None,
        "gmail_message_id": None,
        "gmail_draft_created_at": None,
        "version": 3,
    }
    item.update(overrides)
    return item


def test_review_and_create_saves_review_then_creates_gmail_draft():
    repository = _Repository(_item())
    outreach = _Outreach(repository)
    gmail_repository = _GmailRepository(repository)
    service = OutreachGmailReviewService(
        outreach=outreach,
        repository=repository,
        gmail_repository=gmail_repository,
        gmail=_Gmail(None),
    )

    result = service.review_and_create(
        repository.item["id"],
        expected_version=3,
        to_address="owner@example.com",
        subject="Reviewed subject",
        body="Reviewed body",
    )

    assert outreach.updated["changes"]["status"] == "draft_ready"
    assert outreach.updated["changes"]["subject"] == "Reviewed subject"
    assert outreach.created["expected_version"] == 4
    assert result["gmail_draft_id"] == "new-draft"


def test_recorded_gmail_draft_is_verified_against_gmail():
    repository = _Repository(_item(gmail_draft_id="existing-draft"))
    outreach = _Outreach(repository)
    gmail = _Gmail(GmailDraftResult(draft_id="existing-draft", message_id="msg"))
    service = OutreachGmailReviewService(
        outreach=outreach,
        repository=repository,
        gmail_repository=_GmailRepository(repository),
        gmail=gmail,
    )

    result = service.review_and_create(
        repository.item["id"],
        expected_version=3,
        to_address="owner@example.com",
        subject="Reviewed subject",
        body="Reviewed body",
    )

    assert gmail.checked == ["existing-draft"]
    assert outreach.updated is None
    assert outreach.created is None
    assert result["gmail_draft_id"] == "existing-draft"


def test_missing_recorded_gmail_draft_is_cleared_then_recreated():
    repository = _Repository(_item(gmail_draft_id="stale-draft"))
    outreach = _Outreach(repository)
    gmail_repository = _GmailRepository(repository)
    service = OutreachGmailReviewService(
        outreach=outreach,
        repository=repository,
        gmail_repository=gmail_repository,
        gmail=_Gmail(None),
    )

    result = service.review_and_create(
        repository.item["id"],
        expected_version=3,
        to_address="owner@example.com",
        subject="Reviewed subject",
        body="Reviewed body",
    )

    assert gmail_repository.cleared is True
    assert outreach.updated["expected_version"] == 4
    assert outreach.created["expected_version"] == 5
    assert result["gmail_draft_id"] == "new-draft"


def test_gmail_client_rejects_oauth_account_mismatch(monkeypatch):
    class _Response:
        ok = True

        def json(self):
            return {"emailAddress": "wrong@example.com"}

    monkeypatch.setattr("app.integrations.gmail.requests.get", lambda *args, **kwargs: _Response())
    client = GmailDraftClient(
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        sender_email="mike@lilosgrowth.com",
    )

    try:
        client._assert_sender_account("access-token")
    except GmailDraftError as exc:
        assert "wrong@example.com" in str(exc)
        assert "mike@lilosgrowth.com" in str(exc)
    else:
        raise AssertionError("expected Gmail OAuth account mismatch to be rejected")
