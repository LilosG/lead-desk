from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class OutreachGmailRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def clear_stale_draft(
        self,
        item_id: str,
        *,
        expected_version: int,
        stale_draft_id: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, channel, status,
                               to_address, subject, body, claim_signal,
                               verification_status, verification_note,
                               generation_model, generation_prompt_version,
                               draft_generated_at, gmail_draft_id,
                               gmail_message_id, gmail_draft_created_at,
                               version, created_at, updated_at
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current["version"] != expected_version:
                        return current, True
                    if current.get("gmail_draft_id") != stale_draft_id:
                        return current, True

                    cur.execute(
                        """
                        update outreach_queue
                        set gmail_draft_id = null,
                            gmail_message_id = null,
                            gmail_draft_created_at = null,
                            version = version + 1,
                            updated_at = now()
                        where id = %s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  generation_model, generation_prompt_version,
                                  draft_generated_at, gmail_draft_id,
                                  gmail_message_id, gmail_draft_created_at,
                                  version, created_at, updated_at
                        """,
                        (item_id,),
                    )
                    updated = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (
                            queue_id, place_id, event_type, changes
                        ) values (%s::uuid, %s, 'gmail_draft_missing', %s)
                        """,
                        (
                            item_id,
                            updated["place_id"],
                            Jsonb({"stale_gmail_draft_id": stale_draft_id}),
                        ),
                    )
                    return updated, False
