from pydantic import ValidationError

from app.api.routes.sweeps import SweepCreateRequest


def test_sweep_requires_at_least_one_explicit_city():
    try:
        SweepCreateRequest.model_validate({
            "verticals": ["electrician"],
            "cities": [],
        })
    except ValidationError as exc:
        assert "cities" in str(exc)
    else:
        raise AssertionError("expected an explicit city requirement")


def test_sweep_custom_city_is_accepted_and_preserved():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["Austin, TX, USA"],
    )

    assert request.cities == ["Austin, TX, USA"]


def test_sweep_city_labels_are_deduplicated_case_insensitively():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["Austin, TX, USA", "austin, tx, usa", "Dallas, TX, USA"],
    )

    assert request.cities == ["Austin, TX, USA", "Dallas, TX, USA"]


def test_legacy_county_label_is_not_interpreted_as_default_market():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["San Diego County"],
    )

    assert request.cities == ["San Diego County"]
