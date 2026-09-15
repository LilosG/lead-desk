from app.repositories.outreach import OutreachRepository
from app.repositories.prospects import ProspectRepository
from app.repositories.runs import RunRepository


class OverviewService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        run_repository: RunRepository,
        outreach_repository: OutreachRepository,
    ):
        self.prospect_repository = prospect_repository
        self.run_repository = run_repository
        self.outreach_repository = outreach_repository

    def get_overview(self) -> dict:
        counts = self.prospect_repository.overview_counts()
        counts["outreach_candidates"] = self.outreach_repository.count_candidates()
        counts["latest_run"] = self.run_repository.latest_completed()
        return counts
