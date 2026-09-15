import pytest

from app.services.outreach import OutreachBlocked, OutreachConflict, OutreachService


class FakeRepository:
    def __init__(self):
        self.item = {
            'id': 'queue-1',
            'place_id': 'place-1',
            'channel': 'phone',
            'to_address': '(555) 555-0100',
            'subject': None,
            'body': None,
            'status': 'queued',
            'verification_status': 'pending',
            'gmail_draft_id': None,
            'version': 7,
        }
        self.update_calls = []

    def get_item(self, item_id):
        assert item_id == 'queue-1'
        return dict(self.item)

    def is_suppressed(self, address):
        return False

    def update_item(self, item_id, *, changes, expected_version):
        self.update_calls.append((item_id, changes, expected_version))
        if expected_version != self.item['version']:
            return dict(self.item), True

        self.item.update(changes)
        self.item['version'] += 1
        return dict(self.item), False


def test_phone_item_cannot_become_draft_ready_before_verification():
    repository = FakeRepository()
    service = OutreachService(repository)

    with pytest.raises(OutreachBlocked, match='claim verification is required'):
        service.update_item(
            'queue-1',
            changes={'status': 'draft_ready'},
            expected_version=7,
        )

    assert repository.update_calls == []


def test_verified_phone_item_can_become_draft_ready():
    repository = FakeRepository()
    service = OutreachService(repository)

    result = service.update_item(
        'queue-1',
        changes={
            'verification_status': 'verified',
            'verification_note': 'Manually verified before outreach.',
            'status': 'draft_ready',
        },
        expected_version=7,
    )

    assert result['status'] == 'draft_ready'
    assert result['verification_status'] == 'verified'
    assert result['version'] == 8


def test_stale_outreach_update_is_rejected_before_write():
    repository = FakeRepository()
    service = OutreachService(repository)

    with pytest.raises(OutreachConflict, match='changed since it was loaded'):
        service.update_item(
            'queue-1',
            changes={'status': 'contacted'},
            expected_version=6,
        )

    assert repository.update_calls == []
