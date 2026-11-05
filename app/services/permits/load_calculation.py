"""Dwelling load calculation by the NEC optional method (220.82).

Any permit that adds load to a home can use this: pass the new load as
`added_loads` and it's counted at 100% after the demand factor.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GENERAL_VA_PER_SQ_FT = 3
SMALL_APPLIANCE_CIRCUIT_VA = 1500
LAUNDRY_CIRCUIT_VA = 1500
MINIMUM_DRYER_VA = 5000
FULL_DEMAND_VA = 10000
REMAINDER_DEMAND = 0.4


@dataclass(frozen=True)
class HomeLoads:
    """Nameplate VA. Enter 0 for anything gas or not in the home."""
    square_feet: int
    small_appliance_circuits: int = 2
    laundry_circuits: int = 1
    range_va: int = 0
    cooktop_va: int = 0
    oven_va: int = 0
    dryer_va: int = 0
    water_heater_va: int = 0
    dishwasher_va: int = 0
    disposal_va: int = 0
    microwave_va: int = 0
    hot_tub_or_pool_va: int = 0
    other_va: int = 0
    heating_va: int = 0
    cooling_va: int = 0


@dataclass(frozen=True)
class LoadLine:
    label: str
    basis: str
    va: float


@dataclass(frozen=True)
class LoadCalculation:
    lines: list[LoadLine]
    subtotal_va: float
    first_va: float
    remainder_va: float
    demand_va: float
    hvac_label: str
    hvac_va: float
    added_loads: list[LoadLine] = field(default_factory=list)
    total_va: float = 0
    computed_amps: float = 0
    service_amps: int = 0

    @property
    def spare_amps(self) -> float:
        return self.service_amps - self.computed_amps

    @property
    def percent_of_service(self) -> float:
        return self.computed_amps / self.service_amps * 100


def calculate_load(
    home: HomeLoads,
    *,
    service_amps: int,
    added_loads: list[LoadLine] | None = None,
    volts: int = 240,
) -> LoadCalculation:
    added = list(added_loads or [])
    dryer = max(MINIMUM_DRYER_VA, home.dryer_va) if home.dryer_va else 0
    lines = [
        LoadLine("General lighting", f"{home.square_feet:,} sq ft x {GENERAL_VA_PER_SQ_FT} VA",
                 home.square_feet * GENERAL_VA_PER_SQ_FT),
        LoadLine("Small appliance circuits", f"{home.small_appliance_circuits} x 1,500 VA",
                 home.small_appliance_circuits * SMALL_APPLIANCE_CIRCUIT_VA),
        LoadLine("Laundry circuit", f"{home.laundry_circuits} x 1,500 VA",
                 home.laundry_circuits * LAUNDRY_CIRCUIT_VA),
    ]
    appliances = (
        ("Range", home.range_va), ("Cooktop", home.cooktop_va), ("Oven", home.oven_va),
        ("Dryer", dryer), ("Water heater", home.water_heater_va),
        ("Dishwasher", home.dishwasher_va), ("Disposal", home.disposal_va),
        ("Microwave", home.microwave_va), ("Hot tub or pool", home.hot_tub_or_pool_va),
        ("Other fixed loads", home.other_va),
    )
    lines += [LoadLine(label, "Nameplate", va) for label, va in appliances if va]

    subtotal = sum(line.va for line in lines)
    first = min(subtotal, FULL_DEMAND_VA)
    remainder = (subtotal - first) * REMAINDER_DEMAND
    demand = first + remainder
    # Heating and cooling don't run together, so only the larger counts.
    hvac_label = "Air conditioning" if home.cooling_va >= home.heating_va else "Heating"
    hvac = max(home.cooling_va, home.heating_va)
    total = demand + hvac + sum(load.va for load in added)
    return LoadCalculation(
        lines=lines,
        subtotal_va=subtotal,
        first_va=first,
        remainder_va=remainder,
        demand_va=demand,
        hvac_label=hvac_label,
        hvac_va=hvac,
        added_loads=added,
        total_va=total,
        computed_amps=total / volts,
        service_amps=service_amps,
    )
