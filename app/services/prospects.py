from math import ceil
from typing import Any

from app.repositories.prospects import ProspectRepository
from pipeline import config as market_config
from pipeline.scoring_labels import LABEL_NAMES


class WorkflowVersionConflict(Exception):
    pass


class ProspectService:
    def __init__(self, repository: ProspectRepository):
        self.repository = repository

    def list_prospects(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        tier: str | None,
        city: str | None,
        vertical: str | None,
        contact: str | None,
        trading: bool | None,
        established: bool | None,
        category_opportunity: bool | None,
        label: str | None = None,
        market: str | None = None,
    ) -> dict:
        rows, total = self.repository.list_prospects(
            page=page,
            page_size=page_size,
            search=search,
            tier=tier,
            city=city,
            vertical=vertical,
            contact=contact,
            trading=trading,
            established=established,
            category_opportunity=category_opportunity,
            label=label,
            market=market,
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

    def filter_meta(self) -> dict:
        meta = self.repository.filter_meta()

        # Only what has actually been swept. Presets are listed first so the
        # filter order is stable, but no city list is assumed.
        configured_verticals = list(market_config.VERTICALS)
        observed_verticals = [
            vertical
            for vertical in meta["verticals"]
            if vertical not in configured_verticals
        ]
        seen = set(meta["verticals"])

        return {
            **meta,
            "cities": sorted(meta["cities"]),
            "verticals": [v for v in configured_verticals if v in seen]
            + sorted(observed_verticals),
            "labels": dict(LABEL_NAMES),
        }

    @staticmethod
    def default_workflow() -> dict[str, Any]:
        return {
            "status": "new",
            "priority": "normal",
            "owner": None,
            "next_action": None,
            "next_action_at": None,
            "notes": None,
            "version": 0,
            "created_at": None,
            "updated_at": None,
        }

    def get_prospect(self, place_id: str) -> dict | None:
        prospect = self.repository.get_prospect(place_id)

        if prospect is None:
            return None

        prospect["website_audit"] = self.repository.get_website_audit(place_id)
        prospect["findings"] = self.repository.get_findings(place_id)
        prospect["workflow"] = (
            self.repository.get_workflow(place_id) or self.default_workflow()
        )
        prospect["workflow_events"] = self.repository.get_workflow_events(place_id)

        return prospect

    def update_workflow(
        self,
        place_id: str,
        *,
        changes: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any] | None:
        state, conflict = self.repository.update_workflow(
            place_id,
            changes=changes,
            expected_version=expected_version,
        )

        if conflict:
            raise WorkflowVersionConflict

        return state
