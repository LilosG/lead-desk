from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class AuditReportRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def create_report(
        self,
        *,
        place_id: str,
        title: str,
        selected_signals: list[str],
        snapshot: dict[str, Any],
        source_checked_at: Any,
    ) -> dict[str, Any]:
        query = """
            insert into prospect_audit_reports (
                place_id,
                title,
                selected_signals,
                snapshot,
                source_checked_at
            )
            values (%s, %s, %s, %s, %s)
            returning
                id::text as id,
                place_id,
                report_version,
                status,
                title,
                selected_signals,
                snapshot,
                source_checked_at,
                created_at
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (
                            place_id,
                            title,
                            selected_signals,
                            Jsonb(snapshot),
                            source_checked_at,
                        ),
                    )
                    return cur.fetchone()

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        query = """
            select
                id::text as id,
                place_id,
                report_version,
                status,
                title,
                selected_signals,
                snapshot,
                source_checked_at,
                created_at
            from prospect_audit_reports
            where id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (report_id,))
                return cur.fetchone()

    def list_for_prospect(self, place_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        query = """
            select
                id::text as id,
                place_id,
                report_version,
                status,
                title,
                selected_signals,
                source_checked_at,
                created_at
            from prospect_audit_reports
            where place_id = %s
            order by created_at desc
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id, limit))
                return cur.fetchall()
