from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from app.core.database import pool
from app.repositories.sweeps import (
    SweepAlreadyActiveError,
    SweepRepository,
)
from pipeline import config as market_config
from pipeline import verticals as vertical_config


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

    @staticmethod
    def market_configuration() -> dict[str, Any]:
        verticals = []

        for key, spec in market_config.VERTICALS.items():
            verticals.append(
                {
                    "key": key,
                    "priority": spec["priority"],
                    "query_count": len(spec["queries"]),
                    "has_case_study": bool(spec.get("case_study")),
                }
            )

        return {
            "geo_label": market_config.GEO_LABEL,
            "cities": list(market_config.TARGET_CITIES),
            "verticals": verticals,
            "custom_verticals_enabled": True,
            "custom_cities_enabled": True,
            "grid_scope": "configured_market",
            "pricing": {
                "text_search_per_1000": market_config.COST_PER_1K[
                    "text_search_enterprise"
                ],
                "enterprise_free_monthly": market_config.FREE_TIER_MONTHLY[
                    "enterprise"
                ],
            },
            "execution_enabled": SweepService.execution_enabled(),
        }

    @staticmethod
    def _ordered_verticals(verticals: list[str]) -> list[str]:
        return vertical_config.ordered_verticals(verticals)

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

        if use_grid and cities is not None:
            raise ValueError(
                "Grid search covers the configured market bounding box and cannot be combined with a city-specific sweep. Turn off grid search for selected cities."
            )

        ordered_verticals = self._ordered_verticals(verticals)

        return self.repo.create_job(
            verticals=ordered_verticals,
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
