from app.services.overview import OverviewService


class FakeProspectRepository:
    def overview_counts(self):
        return {
            "prospects": 100,
            "established": 41,
        }


class FakeRunRepository:
    def latest_completed(self):
        return {"id": "run-1"}


class FakeOutreachRepository:
    def count_candidates(self):
        return 13


def test_overview_uses_authoritative_outreach_candidate_count():
    service = OverviewService(
        FakeProspectRepository(),
        FakeRunRepository(),
        FakeOutreachRepository(),
    )

    result = service.get_overview()

    assert result["prospects"] == 100
    assert result["established"] == 41
    assert result["outreach_candidates"] == 13
    assert result["latest_run"] == {"id": "run-1"}
