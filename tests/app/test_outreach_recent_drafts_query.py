from uuid import UUID

from app.services.outreach import OutreachService


class _Repository:
    def __init__(self):
        self.exclude_id = None

    def recent_generated_drafts(self, *, limit=25, exclude_id=None):
        self.exclude_id = exclude_id
        return []


def test_recent_draft_lookup_passes_typed_uuid_to_psycopg_query():
    repository = _Repository()
    service = OutreachService(repository)
    item_id = "99ce2f23-2f0a-4f8a-8bec-ff975261e896"

    rows = service._recent_draft_structures(current_item_id=item_id)

    assert rows == []
    assert isinstance(repository.exclude_id, UUID)
    assert str(repository.exclude_id) == item_id
