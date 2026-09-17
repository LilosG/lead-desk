from pydantic import ValidationError

from app.api.routes.sweeps import SweepCreateRequest


def test_new_sweep_requires_explicit_city_scope():
    try:
        SweepCreateRequest.model_validate({
            "verticals": ["electrician"],
            "cities": None,
        })
    except ValidationError as exc:
        assert "cities" in str(exc)
    else:
        raise AssertionError("new sweeps must require at least one explicit U.S. city")


def test_new_sweep_accepts_google_city_label():
    payload = SweepCreateRequest.model_validate({
        "verticals": ["electrician"],
        "cities": ["Austin, TX, USA"],
    })
    assert payload.cities == ["Austin, TX, USA"]
