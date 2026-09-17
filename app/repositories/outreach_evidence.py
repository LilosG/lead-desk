from __future__ import annotations

from typing import Any

from psycopg_pool import ConnectionPool


class OutreachEvidenceRepository:
    """Read recipient-safe public facts used to ground outreach personalization."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def get(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                b.place_id,
                b.rating,
                b.review_count,
                b.last_review_days,
                b.recent_reviews_90d,
                coalesce(seg.confirmed_trading, false) as confirmed_trading,
                coalesce(seg.established, false) as established
            from businesses b
            left join v_lead_segments seg
              on seg.place_id = b.place_id
            where b.place_id = %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()
