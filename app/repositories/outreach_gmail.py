from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class OutreachGmailRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def open_gmail_drafts(self, created_before: datetime) -> list[dict[str, Any]]:
        """Items we believe are sitting in Gmail's Drafts folder."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select q.id::text as id, q.place_id, q.gmail_draft_id
                    from outreach_queue q
                    where q.gmail_draft_id is not null
                      and q.channel = 'email'
                      and q.status not in ('contacted', 'replied', 'archived', 'suppressed')
                      and q.gmail_draft_created_at < %s
                      and not exists (
                          select 1 from gmail_draft_operations o
                          where o.queue_id = q.id and o.state = 'pending'
                      )
                    """,
                    (created_before,),
                )
                return cur.fetchall()

    def mark_draft_left_gmail(self, item_id: str, draft_id: str) -> bool:
        """The draft is gone from Gmail: sent, or deleted by hand. Treated as contacted."""
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update outreach_queue
                        set status = 'contacted',
                            contacted_at = coalesce(contacted_at, now()),
                            gmail_draft_left_at = now(),
                            version = version + 1,
                            updated_at = now()
                        where id = %s::uuid
                          and gmail_draft_id = %s
                          and status not in ('contacted', 'replied', 'archived', 'suppressed')
                        returning place_id
                        """,
                        (item_id, draft_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return False
                    cur.execute(
                        """
                        insert into outreach_queue_events (
                            queue_id, place_id, event_type, changes
                        ) values (%s::uuid, %s, 'gmail_draft_left', %s)
                        """,
                        (item_id, row["place_id"], Jsonb({"gmail_draft_id": draft_id})),
                    )
                    return True

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

    def record_synced_generated_draft(
        self,
        item_id: str,
        *,
        expected_version: int,
        expected_gmail_draft_id: str,
        subject: str,
        body: str,
        claim_signal: str | None,
        verification_status: str,
        verification_note: str,
        generation_model: str,
        prompt_version: str,
        gmail_message_id: str | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Persist regenerated copy while preserving the existing Gmail draft link."""
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, version, gmail_draft_id
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
                    if current.get("gmail_draft_id") != expected_gmail_draft_id:
                        return current, True

                    cur.execute(
                        """
                        select 1
                        from gmail_draft_operations
                        where queue_id = %s::uuid and state = 'pending'
                        limit 1
                        """,
                        (item_id,),
                    )
                    if cur.fetchone() is not None:
                        return current, True

                    cur.execute(
                        """
                        update outreach_queue
                        set subject = %s,
                            body = %s,
                            claim_signal = %s,
                            verification_status = %s,
                            verification_note = %s,
                            status = 'review_required',
                            generation_model = %s,
                            generation_prompt_version = %s,
                            draft_generated_at = now(),
                            gmail_message_id = coalesce(%s, gmail_message_id),
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
                        (
                            subject,
                            body,
                            claim_signal,
                            verification_status,
                            verification_note,
                            generation_model,
                            prompt_version,
                            gmail_message_id,
                            item_id,
                        ),
                    )
                    updated = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (
                            queue_id, place_id, event_type, changes
                        ) values (%s::uuid, %s, 'draft_regenerated_and_synced', %s)
                        """,
                        (
                            item_id,
                            updated["place_id"],
                            Jsonb(
                                {
                                    "claim_signal": claim_signal,
                                    "verification_status": verification_status,
                                    "generation_model": generation_model,
                                    "prompt_version": prompt_version,
                                    "gmail_draft_id": expected_gmail_draft_id,
                                }
                            ),
                        ),
                    )
                    return updated, False