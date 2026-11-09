import os
import uuid

import pytest

from app.services.demo_autofill import starter_services, suggested_areas, suggested_services
from app.services.demo_sites import DemoSiteService


def test_site_services_come_first_and_are_topped_up_to_six():
    result = suggested_services(["Panel Upgrades", "Commercial Electrical"], "electrician")
    assert result[:2] == ["Panel Upgrades", "Commercial Electrical"]
    assert len(result) == 6
    assert result.count("Panel Upgrades") == 1


def test_starters_skip_services_already_named_differently():
    result = suggested_services(["Water Heater Repair", "Drain & Sewer"], "plumber")
    assert "Water Heater Services" not in result
    assert "Drain Cleaning" not in result
    assert "Sewer Line Repair" not in result
    assert "Leak Detection" in result


def test_generic_job_words_do_not_block_other_starters():
    # "Repair" alone must not knock out every "... Repair" starter.
    result = suggested_services(["Furnace Repair"], "hvac")
    assert "AC Repair" in result
    assert "Furnace Repair" in result and result.count("Furnace Repair") == 1


def test_six_site_services_are_kept_as_is():
    own = ["A1", "B2", "C3", "D4", "E5", "F6"]
    assert suggested_services(own, "electrician") == own


def test_custom_niche_without_starters_keeps_site_services_only():
    assert starter_services("pottery studio") == []
    assert suggested_services(["Wheel Classes"], "pottery studio") == ["Wheel Classes"]
    assert suggested_services([], "") == []


def test_profile_starters_cover_custom_niches_in_known_profiles():
    assert starter_services("dentist")[0] == "General Dentistry"
    assert starter_services("med spa")[0] == "Botox & Neurotoxins"


def test_areas_keep_own_town_first_and_dedupe():
    assert suggested_areas(["Tucson"], ["Marana", "tucson", "Oro Valley", ""]) == ["Tucson", "Marana", "Oro Valley"]
    assert len(suggested_areas(["A"], [f"T{i}" for i in range(20)])) == 8


class _Repo:
    def __init__(self, nearby=None, fail=False):
        self.nearby, self.fail, self.calls = nearby or [], fail, []

    def get_prospect(self, place_id):
        return {"place_id": place_id, "name": "Bright Line Electric", "vertical": "electrician",
                "primary_type": "electrician", "city": "Tucson", "state": "AZ",
                "market": "Tucson, AZ, USA", "lat": 32.22, "lng": -110.97}

    def nearby_towns(self, lat, lng, *, exclude=None, limit=8):
        self.calls.append((lat, lng, exclude))
        if self.fail:
            raise RuntimeError("db down")
        return self.nearby

    def get_website_audit(self, place_id):
        return None


def test_builder_defaults_fill_areas_from_nearby_towns():
    repo = _Repo(nearby=["South Tucson", "Marana", "Oro Valley"])
    defaults = DemoSiteService(repo, None).options_for_prospect("p1")["defaults"]
    assert defaults["service_areas"] == ["Tucson", "South Tucson", "Marana", "Oro Valley"]
    assert repo.calls[0][2] == ["Tucson"]
    assert len(defaults["services"]) == 6


def test_builder_defaults_survive_a_nearby_lookup_failure():
    defaults = DemoSiteService(_Repo(fail=True), None).options_for_prospect("p1")["defaults"]
    assert defaults["service_areas"] == ["Tucson"]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the test database")
def test_nearby_towns_query_orders_by_distance_and_excludes_own_town():
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    from app.repositories.prospects import ProspectRepository

    pool = ConnectionPool(os.environ["DATABASE_URL"], kwargs={"row_factory": dict_row}, open=True)
    tag = uuid.uuid4().hex[:8]
    rows = [
        ("Tucson", 32.2226, -110.9747),
        ("Oro Valley", 32.3909, -110.9665),      # ~19 km
        ("South Tucson", 32.1995, -110.9684),    # ~3 km
        ("south tucson", 32.2000, -110.9690),    # same town, other casing
        ("Phoenix", 33.4484, -112.0740),         # ~170 km, outside radius
    ]
    try:
        with pool.connection() as conn:
            for i, (city, lat, lng) in enumerate(rows):
                conn.execute(
                    "insert into businesses (place_id, name, vertical, city, lat, lng) values (%s, %s, 'electrician', %s, %s, %s)",
                    (f"nearby-{tag}-{i}", f"Biz {i}", city, lat, lng),
                )
        towns = ProspectRepository(pool).nearby_towns(32.2226, -110.9747, exclude=["Tucson"])
        assert towns[:2] == ["South Tucson", "Oro Valley"]
        assert "Phoenix" not in towns and "Tucson" not in towns
    finally:
        with pool.connection() as conn:
            conn.execute("delete from businesses where place_id like %s", (f"nearby-{tag}-%",))
        pool.close()


def test_words_that_name_the_niche_do_not_block_starters():
    roofing = suggested_services(["Roof Repair"], "roofing")
    assert "Roof Replacement" in roofing and "Roof Inspections" in roofing
    dental = suggested_services(["Dental Implants", "Invisalign", "Teeth Whitening"], "dentist")
    assert len(dental) == 6 and "Dental Implants" in dental and dental.count("Teeth Whitening") == 1
