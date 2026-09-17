from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class DemoSiteRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def create_demo(
        self,
        *,
        place_id: str,
        template_key: str,
        slug: str,
        source_snapshot: dict[str, Any],
        content_snapshot: dict[str, Any],
        brand_snapshot: dict[str, Any],
        html_document: str,
    ) -> dict[str, Any]:
        query = """
            insert into prospect_demo_sites (
                place_id,
                template_key,
                slug,
                source_snapshot,
                content_snapshot,
                brand_snapshot,
                html_document
            )
            values (%s, %s, %s, %s, %s, %s, %s)
            returning
                id::text as id,
                place_id,
                demo_version,
                status,
                template_key,
                slug,
                source_snapshot,
                content_snapshot,
                brand_snapshot,
                published_path,
                public_url,
                build_error,
                created_at,
                updated_at,
                published_at
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (
                            place_id,
                            template_key,
                            slug,
                            Jsonb(source_snapshot),
                            Jsonb(content_snapshot),
                            Jsonb(brand_snapshot),
                            html_document,
                        ),
                    )
                    return cur.fetchone()

    def get_demo(self, demo_id: str, *, include_html: bool = False) -> dict[str, Any] | None:
        html_field = ", html_document" if include_html else ""
        query = f"""
            select
                id::text as id,
                place_id,
                demo_version,
                status,
                template_key,
                slug,
                source_snapshot,
                content_snapshot,
                brand_snapshot,
                published_path,
                public_url,
                build_error,
                created_at,
                updated_at,
                published_at
                {html_field}
            from prospect_demo_sites
            where id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (demo_id,))
                return cur.fetchone()

    def list_for_prospect(self, place_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        query = """
            select
                id::text as id,
                place_id,
                demo_version,
                status,
                template_key,
                slug,
                public_url,
                build_error,
                created_at,
                updated_at,
                published_at
            from prospect_demo_sites
            where place_id = %s
            order by created_at desc
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id, limit))
                return cur.fetchall()

    def mark_published(
        self,
        demo_id: str,
        *,
        published_path: str,
        public_url: str,
    ) -> dict[str, Any] | None:
        query = """
            update prospect_demo_sites
            set
                status = 'published',
                published_path = %s,
                public_url = %s,
                build_error = null,
                published_at = now(),
                updated_at = now()
            where id = %s::uuid
              and status = 'ready_for_review'
            returning
                id::text as id,
                place_id,
                demo_version,
                status,
                template_key,
                slug,
                public_url,
                build_error,
                created_at,
                updated_at,
                published_at
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(query, (published_path, public_url, demo_id))
                    return cur.fetchone()

    def mark_build_failed(self, demo_id: str, *, error: str) -> None:
        query = """
            update prospect_demo_sites
            set
                status = 'build_failed',
                build_error = %s,
                updated_at = now()
            where id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(query, (error[:1000], demo_id))
