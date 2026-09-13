from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.errors import UniqueViolation

from psycopg_pool import ConnectionPool


class SweepAlreadyActiveError(RuntimeError):
    pass


class SweepRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def create_job(
        self,
        *,
        verticals: list[str],
        cities: list[str] | None,
        use_grid: bool,
        merge_results: bool,
        crawl_batch: int,
        psi_batch: int,
    ) -> dict[str, Any]:
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into sweep_jobs (
                            verticals,
                            cities,
                            use_grid,
                            merge_results,
                            crawl_batch,
                            psi_batch
                        )
                        values (%s, %s, %s, %s, %s, %s)
                        returning *
                        """,
                        (
                            verticals,
                            cities,
                            use_grid,
                            merge_results,
                            crawl_batch,
                            psi_batch,
                        ),
                    )

                    return cur.fetchone()

        except UniqueViolation as exc:
            raise SweepAlreadyActiveError(
                "A sweep is already queued or running."
            ) from exc

    def get_current(self) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from sweep_jobs
                    where status in ('queued', 'running')
                    order by created_at desc
                    limit 1
                    """
                )

                return cur.fetchone()

    def get_job(self, job_id: UUID | str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from sweep_jobs
                    where id = %s
                    """,
                    (job_id,),
                )

                return cur.fetchone()

    def list_jobs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from sweep_jobs
                    order by created_at desc
                    limit %s
                    """,
                    (limit,),
                )

                return cur.fetchall()

    def request_cancel(self, job_id: UUID | str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update sweep_jobs
                    set
                        cancel_requested = true,
                        updated_at = now()
                    where id = %s
                      and status in ('queued', 'running')
                    returning *
                    """,
                    (job_id,),
                )

                return cur.fetchone()
