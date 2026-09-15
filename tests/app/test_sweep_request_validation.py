from app.api.routes.sweeps import SweepCreateRequest


def test_sweep_cities_drop_california_suffix_tokens():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["carlsbad", "ca"],
    )

    assert request.cities == ["carlsbad"]


def test_sweep_cities_strip_state_suffix_from_city_name():
    request = SweepCreateRequest(
        verticals=["electrician"],
        cities=["Carlsbad CA", "Encinitas, California"],
    )

    assert request.cities == ["Carlsbad", "Encinitas"]
