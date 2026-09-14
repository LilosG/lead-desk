from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class OutreachRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def list_items(self, status: str | None = None) -> tuple[list[dict[str, Any]], int]:
        where = "where q.status = %s" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        query = f"""
            select
                q.id::text as id,
                q.place_id,
                b.name,
                b.city,
                b.vertical,
                w.total_score,
                w.tier,
                w.headline_gap,
                b.phone,
                we.emails_found[1] as email,
                q.channel,
                q.status,
                q.to_address,
                q.subject,
                q.body,
                q.claim_signal,
                q.verification_status,
                q.verification_note,
                exists (
                    select 1
                    from suppression s
                    where lower(s.email) = lower(coalesce(q.to_address, we.emails_found[1], ''))
                ) as suppressed,
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                q.version,
                q.created_at,
                q.updated_at
            from outreach_queue q
            join businesses b on b.place_id = q.place_id
            left join v_lead_worklist w on w.place_id = q.place_id
            left join website_enrichment we on we.place_id = q.place_id
            left join v_lead_findings f on f.place_id = q.place_id
            {where}
            order by
                case q.status
                    when 'review_required' then 1
                    when 'draft_ready' then 2
                    when 'researching' then 3
                    when 'queued' then 4
                    else 5
                end,
                w.total_score desc nulls last,
                q.updated_at desc
        """
        count_query = f"select count(*) from outreach_queue q {where}"
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                cur.execute(count_query, params)
                total = cur.fetchone()['count']
        return rows, total

    def prospect_context(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                b.place_id,
                b.name,
                b.phone,
                we.emails_found,
                coalesce(f.needs_manual_check, false) as needs_manual_check
            from businesses b
            left join website_enrichment we on we.place_id = b.place_id
            left join v_lead_findings f on f.place_id = b.place_id
            where b.place_id = %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def is_suppressed(self, email: str | None) -> bool:
        if not email:
            return False
        query = "select 1 from suppression where lower(email) = lower(%s) limit 1"
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (email,))
                return cur.fetchone() is not None

    def create_item(self, place_id: str, channel: str, to_address: str | None) -> dict[str, Any]:
        query = """
            insert into outreach_queue (place_id, channel, to_address)
            values (%s, %s, %s)
            on conflict (place_id, channel) do update
            set to_address = coalesce(excluded.to_address, outreach_queue.to_address),
                updated_at = now()
            returning id::text as id, place_id, channel, status, to_address,
                      subject, body, claim_signal, verification_status,
                      verification_note, version, created_at, updated_at
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(query, (place_id, channel, to_address))
                    row = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'queued', %s)
                        """,
                        (row['id'], place_id, Jsonb({'channel': channel, 'to_address': to_address})),
                    )
        return row

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        query = """
            select id::text as id, place_id, channel, status, to_address,
                   subject, body, claim_signal, verification_status,
                   verification_note, version, created_at, updated_at
            from outreach_queue
            where id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (item_id,))
                return cur.fetchone()

    def update_item(self, item_id: str, *, changes: dict[str, Any], expected_version: int) -> tuple[dict[str, Any] | None, bool]:
        editable = {
            'status', 'to_address', 'subject', 'body', 'claim_signal',
            'verification_status', 'verification_note'
        }
        safe = {key: value for key, value in changes.items() if key in editable}

        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, channel, status, to_address,
                               subject, body, claim_signal, verification_status,
                               verification_note, version, created_at, updated_at
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current['version'] != expected_version:
                        return current, True

                    state = dict(current)
                    state.update(safe)
                    cur.execute(
                        """
                        update outreach_queue
                        set status=%s, to_address=%s, subject=%s, body=%s,
                            claim_signal=%s, verification_status=%s,
                            verification_note=%s, version=version+1,
                            updated_at=now()
                        where id=%s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  version, created_at, updated_at
                        """,
                        (
                            state['status'], state['to_address'], state['subject'],
                            state['body'], state['claim_signal'],
                            state['verification_status'], state['verification_note'],
                            item_id,
                        ),
                    )
                    updated = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'updated', %s)
                        """,
                        (item_id, updated['place_id'], Jsonb(safe)),
                    )
        return updated, False
