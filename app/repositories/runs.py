from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool


RUN_SELECT = """
    select
        r.id,
        r.started_at,
        r.finished_at,
        r.geo_label,
        r.verticals,
        r.grid_points,
        r.status,
        r.stage,
        r.dry_run,
        r.notes,

        r.businesses_discovered,
        count(distinct s.place_id) as businesses_scored,
        r.websites_crawled,
        r.psi_completed,

        count(*) filter (where s.tier = 'A') as tier_a,
        count(*) filter (where s.tier = 'B') as tier_b,
        count(*) filter (where s.tier = 'C') as tier_c,
        count(*) filter (where s.tier = 'D') as tier_d,

        round(avg(s.total_score), 1) as avg_score,

        r.api_calls_search,
        r.api_calls_details,
        r.api_calls_psi,
        r.est_cost_usd,

        r.discovery_finished_at,
        r.crawl_finished_at,
        r.psi_finished_at

    from runs r
    left join scores s
      on s.run_id = r.id
"""


RUN_GROUP_BY = """
    group by
        r.id,
        r.started_at,
        r.finished_at,
        r.geo_label,
        r.verticals,
        r.grid_points,
        r.status,
        r.stage,
        r.dry_run,
        r.notes,
        r.businesses_discovered,
        r.websites_crawled,
        r.psi_completed,
        r.api_calls_search,
        r.api_calls_details,
        r.api_calls_psi,
        r.est_cost_usd,
        r.discovery_finished_at,
        r.crawl_finished_at,
        r.psi_finished_at
"""


class RunRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def latest_completed(self) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from v_latest_completed_run limit 1")
                return cur.fetchone()

    def list_runs(
        self,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from runs")
                total = cur.fetchone()["count"]

                cur.execute(
                    RUN_SELECT
                    + RUN_GROUP_BY
                    + """
                      order by r.started_at desc
                      limit %s offset %s
                      """,
                    (page_size, offset),
                )
                rows = cur.fetchall()

        return rows, total

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    RUN_SELECT
                    + """
                      where r.id = %s
                      """
                    + RUN_GROUP_BY,
                    (run_id,),
                )
                return cur.fetchone()
