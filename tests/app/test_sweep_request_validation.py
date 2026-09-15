import pytest
from pydantic import ValidationError

from app.api.routes.sweeps import SweepCreateRequest


def test_sweep_cities_drop_california_suffix_tokens():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["carlsbad", "ca"],
    )

    assert request.cities == ["Carlsbad"]


def test_sweep_cities_strip_state_suffix_from_city_name():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["Carlsbad CA", "Encinitas, California"],
    )

    assert request.cities == ["Carlsbad", "Encinitas"]


def test_sweep_county_label_means_all_configured_cities():
    request = SweepCreateRequest(
        verticals=["electrician", "plumber"],
        cities=["San Diego County"],
    )

    assert request.cities is None


def test_sweep_unknown_city_is_rejected():
    with pytest.raises(ValidationError, match="unsupported sweep city"):
        SweepCreateRequest(
            verticals=["electrician"],
            cities=["Not A Configured City"],
        )
