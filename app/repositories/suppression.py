from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class SuppressionRepository:
    """The never-contact list. Emails are stored lowercase."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def list(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select email, reason, added_at from suppression order by added_at desc"
                )
                return cur.fetchall()

    def add(self, email: str, reason: str | None) -> dict[str, Any]:
        """Add an email and close every open queue item addressed to it."""
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into suppression (email, reason)
                        values (%s, %s)
                        on conflict (email) do update
                          set reason = coalesce(excluded.reason, suppression.reason)
                        returning email, reason, added_at
                        """,
                        (email, reason),
                    )
                    row = cur.fetchone()
                    cur.execute(
                        """
                        update outreach_queue
                        set status = 'suppressed', version = version + 1, updated_at = now()
                        where lower(coalesce(to_address, '')) = %s and status <> 'suppressed'
                        returning id::text as id, place_id
                        """,
                        (email,),
                    )
                    for item in cur.fetchall():
                        cur.execute(
                            """
                            insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                            values (%s::uuid, %s, 'do_not_contact', %s)
                            """,
                            (item["id"], item["place_id"], Jsonb({"status": "suppressed"})),
                        )
                    return row

    def remove(self, email: str) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from suppression where email = %s", (email,))
                return cur.rowcount > 0
