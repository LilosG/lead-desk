from math import ceil
from uuid import UUID

from app.repositories.runs import RunRepository


class RunService:
    def __init__(self, repository: RunRepository):
        self.repository = repository

    def list_runs(self, *, page: int, page_size: int) -> dict:
        rows, total = self.repository.list_runs(
            page=page,
            page_size=page_size,
        )

        return {
            "items": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": ceil(total / page_size) if total else 0,
            },
        }

    def get_run(self, run_id: UUID) -> dict | None:
        return self.repository.get_run(run_id)
