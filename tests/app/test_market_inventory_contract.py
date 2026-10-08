from pathlib import Path

from app.services.prospects import ProspectService
from app.services.sweeps import SweepService
from pipeline import config as market_config
from pipeline import verticals as vertical_config


class FakeProspectRepository:
    def filter_meta(self):
        return {
            "cities": ["Carlsbad", "Unlisted City"],
            "verticals": ["electrician", "custom_vertical"],
            "tiers": ["A", "B", "C", "D"],
            "total_prospects": 42,
        }


def test_prospect_meta_lists_only_swept_markets_and_niches():
    meta = ProspectService(FakeProspectRepository()).filter_meta()

    # No region is assumed: only cities and niches that were actually swept.
    assert meta["cities"] == ["Carlsbad", "Unlisted City"]
    assert meta["verticals"] == ["electrician", "custom_vertical"]
    assert market_config.TARGET_CITIES == []
    assert "established" in meta["labels"]
    assert meta["total_prospects"] == 42


def test_sweep_vertical_order_is_config_driven_and_deduplicated():
    ordered = SweepService._ordered_verticals(
        ["handyman", "electrician", "plumber", "electrician"]
    )

    assert ordered == ["electrician", "plumber", "handyman"]


def test_sweep_vertical_order_accepts_and_normalizes_custom_verticals():
    ordered = SweepService._ordered_verticals(
        ["Personal Injury Attorney", "electrician", "Med Spa", "med-spa"]
    )

    assert ordered == ["electrician", "med_spa", "personal_injury_attorney"]


def test_custom_vertical_uses_entered_phrase_as_default_query():
    assert vertical_config.vertical_queries("Mobile Dog Groomer") == [
        "mobile dog groomer"
    ]
    assert vertical_config.vertical_priority("Mobile Dog Groomer") > max(
        spec["priority"] for spec in market_config.VERTICALS.values()
    )
    assert vertical_config.vertical_profile("Mobile Dog Groomer") == (
        "generic_local_business"
    )


def test_non_trade_presets_have_their_own_profiles():
    assert vertical_config.vertical_profile("Real Estate Agent") == "real_estate"
    assert vertical_config.vertical_profile("med spa") == "medical_aesthetic"
    assert vertical_config.vertical_profile("Dentist") == "dental"
    assert vertical_config.vertical_profile("electrician") == "home_service"
    # Generic profile is the union of every niche's vocabulary, so a custom
    # niche errs toward NOT claiming missing offering pages.
    generic = set(market_config.NICHE_PROFILES["generic_local_business"]["offering_words"])
    for name, profile in market_config.NICHE_PROFILES.items():
        assert set(profile["offering_words"]) <= generic, name


def test_custom_vertical_discovery_does_not_use_home_service_noise_exclusions():
    discover = Path("pipeline/discover.py").read_text()

    assert "if not V.is_preset(vertical):" in discover
    assert "return False" in discover
    assert "V.vertical_queries(vertical)" in discover


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


def test_business_vertical_memberships_are_durable_and_backfilled():
    migration = Path(
        "sql/migrations/013_business_vertical_memberships.sql"
    ).read_text().lower()

    assert "create table business_vertical_memberships" in migration
    assert "primary key (place_id, vertical)" in migration
    assert "on conflict (place_id, vertical) do nothing" in migration
    assert "from businesses b" in migration


def test_pipeline_records_all_matched_verticals_and_recomputes_canonical():
    discover = Path("pipeline/discover.py").read_text()
    store = Path("pipeline/store.py").read_text()

    assert '"matched_verticals": [vertical]' in discover
    assert "merge_vertical_memberships" in discover
    assert "merge_vertical_memberships(found[pid], rec)" in discover
    assert 'r.pop("matched_verticals", None)' in store
    assert "insert into business_vertical_memberships" in store
    assert "canonical_vertical" in store
    assert "V.vertical_priority(vertical)" in store


def test_prospect_vertical_filter_uses_membership_relation():
    repository = Path("app/repositories/prospects.py").read_text()

    assert "from business_vertical_memberships bvm" in repository
    assert "bvm.vertical = %(vertical)s" in repository
    assert 'conditions.append(sql.SQL("w.vertical = %(vertical)s"))' not in repository
