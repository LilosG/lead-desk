from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from app.core.database import pool
from app.repositories.sweeps import (
    SweepAlreadyActiveError,
    SweepRepository,
)


class SweepExecutionDisabledError(RuntimeError):
    pass


class SweepService:
    def __init__(self) -> None:
        self.repo = SweepRepository(pool)

    @staticmethod
    def execution_enabled() -> bool:
        return os.getenv(
            "SWEEP_EXECUTION_ENABLED",
            "false",
        ).lower() in {"1", "true", "yes", "on"}

    def create(
        self,
        *,
        verticals: list[str],
        cities: list[str] | None,
        use_grid: bool,
        merge_results: bool,
        crawl_batch: int,
        psi_batch: int,
    ) -> dict[str, Any]:
        if not self.execution_enabled():
            raise SweepExecutionDisabledError(
                "Sweep execution is currently disabled."
            )

        return self.repo.create_job(
            verticals=verticals,
            cities=cities,
            use_grid=use_grid,
            merge_results=merge_results,
            crawl_batch=crawl_batch,
            psi_batch=psi_batch,
        )

    def current(self) -> dict[str, Any] | None:
        return self.repo.get_current()

    def list(self, limit: int = 25) -> list[dict[str, Any]]:
        return self.repo.list_jobs(limit)

    def cancel(self, job_id: UUID) -> dict[str, Any] | None:
        return self.repo.request_cancel(job_id)


__all__ = [
    "SweepAlreadyActiveError",
    "SweepExecutionDisabledError",
    "SweepService",
]
