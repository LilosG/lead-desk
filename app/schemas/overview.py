from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LatestRunSummary(BaseModel):
    id: UUID
    started_at: datetime
    finished_at: datetime | None
    geo_label: str
    verticals: list[str]
    status: str
    stage: str | None
    businesses_discovered: int
    websites_crawled: int
    psi_completed: int
    api_calls_search: int
    api_calls_details: int
    api_calls_psi: int
    est_cost_usd: float


class OverviewResponse(BaseModel):
    prospects: int

    tier_a: int
    tier_b: int
    tier_c: int
    tier_d: int

    emailable: int
    phone_only: int
    no_contact: int

    no_website: int
    confirmed_trading: int
    category_opportunity: int
    established: int
    outreach_candidates: int
    manual_check: int

    established_emailable: int
    established_phone_only: int

    latest_run: LatestRunSummary | None
