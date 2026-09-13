from math import ceil

from app.repositories.prospects import ProspectRepository


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
        contact: str | None,
        trading: bool | None,
        established: bool | None,
        category_opportunity: bool | None,
    ) -> dict:
        rows, total = self.repository.list_prospects(
            page=page,
            page_size=page_size,
            search=search,
            tier=tier,
            city=city,
            contact=contact,
            trading=trading,
            established=established,
            category_opportunity=category_opportunity,
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
        return self.repository.filter_meta()

    def get_prospect(self, place_id: str) -> dict | None:
        prospect = self.repository.get_prospect(place_id)

        if prospect is None:
            return None

        prospect["website_audit"] = self.repository.get_website_audit(
            place_id
        )

        prospect["findings"] = self.repository.get_findings(
            place_id
        )

        return prospect
