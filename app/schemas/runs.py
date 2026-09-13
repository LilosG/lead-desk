from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import Pagination


class RunListItem(BaseModel):
    id: UUID
    started_at: datetime
    finished_at: datetime | None

    geo_label: str
    verticals: list[str]

    status: str
    stage: str | None
    dry_run: bool

    businesses_discovered: int
    businesses_scored: int
    websites_crawled: int
    psi_completed: int

    tier_a: int
    tier_b: int
    tier_c: int
    tier_d: int

    avg_score: float | None

    api_calls_search: int
    api_calls_details: int
    api_calls_psi: int
    est_cost_usd: float


class RunListResponse(BaseModel):
    items: list[RunListItem]
    pagination: Pagination


class RunDetail(RunListItem):
    grid_points: int | None
    notes: str | None

    discovery_finished_at: datetime | None
    crawl_finished_at: datetime | None
    psi_finished_at: datetime | None
