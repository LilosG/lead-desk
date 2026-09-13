from app.repositories.prospects import ProspectRepository
from app.repositories.runs import RunRepository


class OverviewService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        run_repository: RunRepository,
    ):
        self.prospect_repository = prospect_repository
        self.run_repository = run_repository

    def get_overview(self) -> dict:
        counts = self.prospect_repository.overview_counts()
        counts["latest_run"] = self.run_repository.latest_completed()
        return counts
