"""EV permit packets: the code math, the flags, the PDF and the routes."""
from __future__ import annotations

import re

import pytest

from app.services.permits.circuits import WIRES, conduit_size, size_breaker, size_circuit, voltage_drop
from app.services.permits.ev_charger import EvJob, build_ev_packet
from app.services.permits.ev_packet_pdf import render_ev_packet_pdf
from app.services.permits.load_calculation import HomeLoads, LoadLine, calculate_load

HOME = HomeLoads(
    square_feet=3100, range_va=12000, dryer_va=5000, water_heater_va=4500, dishwasher_va=1200,
    disposal_va=900, microwave_va=1500, hot_tub_or_pool_va=1800, cooling_va=7200,
)


def _job(**changes) -> EvJob:
    values = dict(
        customer="Sample Homeowner", address="123 Sample St", contractor="Sample Electric, LLC",
        license_number="ROC 000000", home=HOME, service_amps=200, open_breaker_spaces=2,
        charger_amps=48, location="detached_garage", run_ft=58, trench_ft=55,
    )
    return EvJob(**{**values, **changes})


def _payload(**changes) -> dict:
    home = {"square_feet": 2000, "range_va": 12000, "cooling_va": 7200}
    values = dict(
        customer="Sample", address="123 Sample St", contractor="Sample Electric",
        license_number="ROC 000000", home=home, service_amps=200, open_breaker_spaces=4,
        charger_amps=40, location="attached_garage", run_ft=30, trench_ft=0,
    )
    return {**values, **changes}


def test_worked_load_calculation_matches_the_sample_packet():
    load = calculate_load(HOME, service_amps=200,
                          added_loads=[LoadLine("EV charger", "48 A", 11520)])
    assert load.subtotal_va == 40700
    assert load.demand_va == 22280
    assert load.total_va == 41000
    assert round(load.computed_amps, 1) == 170.8
    assert round(load.spare_amps, 1) == 29.2


def test_electric_dryer_has_a_5000_va_minimum_and_gas_counts_nothing():
    electric = calculate_load(HomeLoads(square_feet=1000, dryer_va=3000), service_amps=100)
    gas = calculate_load(HomeLoads(square_feet=1000), service_amps=100)
    assert electric.subtotal_va - gas.subtotal_va == 5000


def test_only_the_larger_of_heating_and_cooling_counts():
    load = calculate_load(HomeLoads(square_feet=1000, heating_va=9000, cooling_va=5000), service_amps=100)
    assert load.hvac_va == 9000
    assert load.hvac_label == "Heating"


def test_a_small_home_stays_inside_the_first_10000_va():
    load = calculate_load(HomeLoads(square_feet=1000), service_amps=100)
    assert load.subtotal_va == 7500
    assert load.remainder_va == 0
    assert load.demand_va == 7500


@pytest.mark.parametrize("amps,breaker", [(16, 20), (24, 30), (32, 40), (40, 50), (48, 60), (64, 80), (80, 100)])
def test_breaker_covers_125_percent_of_the_charger(amps, breaker):
    assert size_breaker(amps * 1.25) == breaker


@pytest.mark.parametrize("amps,wire,ground", [(32, "8", "10"), (40, "8", "10"), (48, "6", "10"), (64, "4", "8")])
def test_wire_and_ground_sizes(amps, wire, ground):
    circuit = size_circuit(amps, 20, continuous=True)
    assert (circuit.wire.size, circuit.ground) == (wire, ground)


def test_voltage_drop_matches_the_sample_packet():
    six = next(wire for wire in WIRES if wire.size == "6")
    volts, percent = voltage_drop(48, 58, six)
    assert round(volts, 1) == 2.7
    assert round(percent, 1) == 1.1


def test_a_long_run_upsizes_the_wire_for_voltage_drop():
    circuit = size_circuit(48, 200, continuous=True)
    assert circuit.upsized_for_voltage_drop
    assert circuit.wire.size == "4"
    assert round(circuit.voltage_drop_percent, 1) == 2.5


def test_conduit_has_a_three_quarter_inch_minimum_and_grows_with_wire():
    assert conduit_size(size_circuit(32, 20, continuous=True), "EMT") == '3/4"'
    assert conduit_size(size_circuit(80, 20, continuous=True), "PVC") == '1"'


def test_passing_job_has_no_fix_items():
    packet = build_ev_packet(_job())
    assert packet.ready
    assert packet.disconnect_amps == 60
    assert any("85% of capacity" in flag for flag in packet.flags)
    assert any("811" in flag for flag in packet.flags)


def test_overloaded_service_fails_and_explains_why():
    packet = build_ev_packet(_job(service_amps=100))
    assert not packet.ready
    assert any("over capacity by 70.8 A" in flag for flag in packet.flags)


def test_a_full_panel_fails_the_spaces_check():
    packet = build_ev_packet(_job(open_breaker_spaces=1))
    assert not packet.ready
    assert any("two open spaces" in flag for flag in packet.flags)


def test_attached_garage_under_60_amps_skips_the_disconnect():
    packet = build_ev_packet(_job(location="attached_garage", charger_amps=40, trench_ft=0))
    assert packet.disconnect_amps is None
    assert packet.underground_conduit is None
    assert not any("811" in flag for flag in packet.flags)


@pytest.mark.parametrize("location", ["attached_garage", "detached_garage", "exterior_wall"])
@pytest.mark.parametrize("trench_ft", [0, 40])
def test_pdf_is_seven_pages_for_every_layout(location, trench_ft):
    pdf = render_ev_packet_pdf(build_ev_packet(_job(location=location, trench_ft=trench_ft)))
    assert pdf.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 7


def test_pdf_survives_markup_in_typed_text():
    pdf = render_ev_packet_pdf(build_ev_packet(_job(contractor="Smith & Sons <LLC>")))
    assert pdf.startswith(b"%PDF")


def test_check_route_returns_sizing(client):
    response = client.post("/api/permit-packets/ev/check", json=_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert (body["breaker"], body["wire"]) == (50, "#8 AWG Cu")


def test_pdf_route_returns_a_download(client):
    response = client.post("/api/permit-packets/ev/pdf", json=_payload())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_routes_need_a_login(public_client):
    assert public_client.post("/api/permit-packets/ev/check", json=_payload()).status_code == 401


def test_trench_longer_than_the_run_is_refused(client):
    assert client.post("/api/permit-packets/ev/check", json=_payload(trench_ft=99)).status_code == 422


def test_charger_outside_level_2_range_is_refused(client):
    assert client.post("/api/permit-packets/ev/check", json=_payload(charger_amps=200)).status_code == 422
