from fastapi import APIRouter

from app.core.database import pool
from app.repositories.prospects import ProspectRepository
from app.repositories.runs import RunRepository
from app.schemas.overview import OverviewResponse
from app.services.overview import OverviewService


router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewResponse)
def overview() -> dict:
    service = OverviewService(
        ProspectRepository(pool),
        RunRepository(pool),
    )
    return service.get_overview()
