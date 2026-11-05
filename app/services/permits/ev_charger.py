"""Residential Level 2 EV charger permit: the job, the checks and the flags."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.permits.circuits import Circuit, conduit_size, size_circuit
from app.services.permits.load_calculation import (
    HomeLoads,
    LoadCalculation,
    LoadLine,
    calculate_load,
)

VOLTS = 240
HIGH_SERVICE_USE_PERCENT = 80
HIGH_VOLTAGE_DROP_PERCENT = 3
DISCONNECT_REQUIRED_ABOVE_AMPS = 60
BURIAL_DEPTH_IN = 18

Location = Literal["attached_garage", "detached_garage", "exterior_wall"]
LOCATION_LABELS = {
    "attached_garage": "attached garage",
    "detached_garage": "detached garage",
    "exterior_wall": "exterior wall",
}


@dataclass(frozen=True)
class EvJob:
    customer: str
    address: str
    contractor: str
    license_number: str
    home: HomeLoads
    service_amps: int
    open_breaker_spaces: int
    charger_amps: int
    location: Location
    run_ft: int
    trench_ft: int


@dataclass(frozen=True)
class Check:
    name: str
    result: str
    passed: bool


@dataclass(frozen=True)
class EvPacket:
    job: EvJob
    charger_va: int
    load: LoadCalculation
    circuit: Circuit
    disconnect_amps: int | None
    underground_conduit: str | None
    interior_conduit: str
    interior_ft: int
    checks: list[Check]
    flags: list[str]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)


def _flags(job: EvJob, load: LoadCalculation, circuit: Circuit, disconnect: int | None) -> list[str]:
    flags = ["Check the existing loads against the home. They drive the service result."]
    if load.computed_amps > job.service_amps:
        flags.append(
            f"The service is over capacity by {-load.spare_amps:.1f} A. It needs a service upgrade, "
            "a smaller charger or load management before this can be submitted."
        )
    elif load.percent_of_service >= HIGH_SERVICE_USE_PERCENT:
        flags.append(
            f"Service is at {load.percent_of_service:.0f}% of capacity. "
            "Review it before adding this load."
        )
    if job.open_breaker_spaces < 2:
        flags.append("The panel needs two open spaces for this breaker.")
    if circuit.upsized_for_voltage_drop:
        flags.append(
            f"Wire was upsized to #{circuit.wire.size} AWG for voltage drop. "
            "Confirm the equipment ground size is increased to match."
        )
    if circuit.voltage_drop_percent > HIGH_VOLTAGE_DROP_PERCENT:
        flags.append(
            f"Voltage drop is {circuit.voltage_drop_percent:.1f}% even at the largest wire size. "
            "Shorten the run or redesign the circuit."
        )
    if job.trench_ft:
        flags.append("Call 811 before trenching and field verify the route.")
    if disconnect:
        flags.append("Confirm the disconnect location and type with the city.")
    if job.location == "detached_garage":
        flags.append("Confirm grounding requirements at the detached garage.")
    flags.append("Confirm the city's adopted code edition.")
    return flags


def build_ev_packet(job: EvJob) -> EvPacket:
    charger_va = job.charger_amps * VOLTS
    load = calculate_load(
        job.home,
        service_amps=job.service_amps,
        added_loads=[LoadLine("EV charger", f"{job.charger_amps} A x {VOLTS} V, 100%", charger_va)],
        volts=VOLTS,
    )
    circuit = size_circuit(job.charger_amps, job.run_ft, continuous=True, volts=VOLTS)
    disconnect = (
        circuit.breaker
        if job.location == "detached_garage" or job.charger_amps > DISCONNECT_REQUIRED_ABOVE_AMPS
        else None
    )
    checks = [
        Check("Service capacity",
              f"{load.computed_amps:.1f} A computed on a {job.service_amps} A service",
              load.computed_amps <= job.service_amps),
        Check("Panel spaces", f"{job.open_breaker_spaces} open, 2 needed",
              job.open_breaker_spaces >= 2),
        Check("Circuit",
              f"{circuit.breaker} A breaker for a {job.charger_amps} A continuous load "
              f"({job.charger_amps} A x 125%)",
              circuit.breaker >= circuit.required_amps),
        Check("Conductors",
              f"#{circuit.wire.size} AWG Cu, rated {circuit.wire.ampacity_75c} A at 75\N{DEGREE SIGN}C",
              circuit.wire.ampacity_75c >= circuit.breaker),
        Check("Voltage drop",
              f"{circuit.voltage_drop_volts:.1f} V, or {circuit.voltage_drop_percent:.1f}%, over {job.run_ft} ft",
              circuit.voltage_drop_percent <= HIGH_VOLTAGE_DROP_PERCENT),
    ]
    return EvPacket(
        job=job,
        charger_va=charger_va,
        load=load,
        circuit=circuit,
        disconnect_amps=disconnect,
        underground_conduit=conduit_size(circuit, "PVC") if job.trench_ft else None,
        interior_conduit=conduit_size(circuit, "EMT"),
        interior_ft=max(job.run_ft - job.trench_ft, 0),
        checks=checks,
        flags=_flags(job, load, circuit, disconnect),
    )
