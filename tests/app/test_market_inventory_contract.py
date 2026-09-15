from pathlib import Path

from app.services.prospects import ProspectService
from app.services.sweeps import SweepService
from pipeline import config as market_config


class FakeProspectRepository:
    def filter_meta(self):
        return {
            "cities": ["Carlsbad", "Unlisted City"],
            "verticals": ["electrician", "custom_vertical"],
            "tiers": ["A", "B", "C", "D"],
            "total_prospects": 42,
        }


def test_prospect_meta_keeps_configured_market_and_observed_extras():
    meta = ProspectService(FakeProspectRepository()).filter_meta()

    assert meta["cities"][: len(market_config.TARGET_CITIES)] == market_config.TARGET_CITIES
    assert meta["verticals"][: len(market_config.VERTICALS)] == list(market_config.VERTICALS)
    assert "Unlisted City" in meta["cities"]
    assert "custom_vertical" in meta["verticals"]
    assert meta["total_prospects"] == 42


def test_sweep_vertical_order_is_config_driven_and_deduplicated():
    ordered = SweepService._ordered_verticals(
        ["handyman", "electrician", "plumber", "electrician"]
    )

    assert ordered == ["electrician", "plumber", "handyman"]


def test_sweep_vertical_order_rejects_unknown_vertical():
    try:
        SweepService._ordered_verticals(["electrician", "not-real"])
    except ValueError as exc:
        assert "not-real" in str(exc)
    else:
        raise AssertionError("unknown vertical should be rejected")


def test_text_search_pricing_matches_atmosphere_field_mask():
    assert "places.reviews" in market_config.SEARCH_FIELD_MASK
    assert market_config.COST_PER_1K["text_search_enterprise"] == 40.00
    assert market_config.FREE_TIER_MONTHLY["enterprise"] == 1_000


def test_operational_views_use_latest_completed_score_per_prospect():
    views = Path("sql/views.sql").read_text()
    migration = Path("sql/migrations/012_cumulative_market_inventory.sql").read_text()

    for sql in (views, migration):
        normalized = " ".join(sql.lower().split())
        assert "distinct on (s.place_id)" in normalized
        assert "join runs r" in normalized
        assert "r.status = 'completed'" in normalized
        assert "join v_latest_completed_run r on r.id = s.run_id" not in normalized
