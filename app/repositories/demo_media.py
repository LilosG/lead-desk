from typing import Any

from psycopg_pool import ConnectionPool


class DemoMediaRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def create_media(
        self,
        *,
        place_id: str,
        role: str,
        source: str,
        model: str | None,
        prompt_version: str | None,
        prompt_text: str | None,
        storage_path: str,
        public_url: str,
    ) -> dict[str, Any]:
        query = """
            insert into prospect_demo_media (
                place_id, role, source, model, prompt_version,
                prompt_text, storage_path, public_url
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning
                id::text as id,
                place_id,
                role,
                source,
                model,
                prompt_version,
                public_url,
                created_at
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (
                            place_id,
                            role,
                            source,
                            model,
                            prompt_version,
                            prompt_text,
                            storage_path,
                            public_url,
                        ),
                    )
                    return cur.fetchone()

    def list_for_prospect(self, place_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        query = """
            select
                id::text as id,
                place_id,
                role,
                source,
                model,
                prompt_version,
                public_url,
                created_at
            from prospect_demo_media
            where place_id = %s
            order by created_at desc
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id, limit))
                return cur.fetchall()
