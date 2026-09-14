from app.repositories.outreach import OutreachRepository


class OutreachConflict(RuntimeError):
    pass


class OutreachBlocked(RuntimeError):
    pass


class OutreachService:
    def __init__(self, repository: OutreachRepository):
        self.repository = repository

    def list_candidates(self, limit: int = 100) -> dict:
        items = self.repository.list_candidates(limit=limit)
        return {'items': items, 'total': len(items)}

    def list_items(self, status: str | None = None) -> dict:
        items, total = self.repository.list_items(status=status)
        return {'items': items, 'total': total}

    def create_item(self, place_id: str, channel: str, to_address: str | None) -> dict | None:
        prospect = self.repository.prospect_context(place_id)
        if prospect is None:
            return None

        if channel == 'email':
            address = to_address or ((prospect.get('emails_found') or [None])[0])
            if not address:
                raise OutreachBlocked('prospect has no usable email address')
            if self.repository.is_suppressed(address):
                raise OutreachBlocked('email address is suppressed')
            to_address = address
        elif channel == 'phone':
            if not prospect.get('phone'):
                raise OutreachBlocked('prospect has no phone number')
            to_address = to_address or prospect['phone']

        item = self.repository.create_item(place_id, channel, to_address)
        return item

    def update_item(self, item_id: str, *, changes: dict, expected_version: int) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None

        effective_address = changes.get('to_address', current.get('to_address'))
        if current['channel'] == 'email' and self.repository.is_suppressed(effective_address):
            raise OutreachBlocked('email address is suppressed')

        next_status = changes.get('status', current['status'])
        verification = changes.get(
            'verification_status',
            current['verification_status'],
        )
        subject = changes.get('subject', current.get('subject'))
        body = changes.get('body', current.get('body'))

        if next_status in {'draft_ready', 'approved'}:
            if current['channel'] == 'email' and (not subject or not body):
                raise OutreachBlocked('email draft requires both subject and body')
            if verification not in {'verified', 'not_required'}:
                raise OutreachBlocked('claim verification is required before a draft can be ready')

        updated, conflict = self.repository.update_item(
            item_id,
            changes=changes,
            expected_version=expected_version,
        )
        if conflict:
            raise OutreachConflict('outreach item changed since it was loaded')
        return updated
