"""Branch circuit sizing shared by electrical permit types.

Copper THWN-2 at the 75 C column, single-phase. Results are drafts for a
licensed electrician's review.
"""
from __future__ import annotations

from dataclasses import dataclass

CONTINUOUS_FACTOR = 1.25
MAX_VOLTAGE_DROP_PERCENT = 3.0
# Resistance constant for copper in the voltage drop formula.
COPPER_K = 12.9

STANDARD_BREAKERS = (15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 125)


@dataclass(frozen=True)
class Wire:
    size: str
    ampacity_75c: int
    circular_mils: int
    area_sq_in: float


# NEC 310.16 ampacity, Chapter 9 Table 8 area, Chapter 9 Table 5 THWN-2 area.
WIRES = (
    Wire("14", 20, 4110, 0.0097),
    Wire("12", 25, 6530, 0.0133),
    Wire("10", 35, 10380, 0.0211),
    Wire("8", 50, 16510, 0.0366),
    Wire("6", 65, 26240, 0.0507),
    Wire("4", 85, 41740, 0.0824),
    Wire("3", 100, 52620, 0.0973),
    Wire("2", 115, 66360, 0.1158),
    Wire("1", 130, 83690, 0.1562),
)

# NEC 250.122, largest breaker each equipment ground size covers.
GROUND_SIZES = ((15, "14"), (20, "12"), (60, "10"), (100, "8"), (200, "6"))

# NEC Chapter 9 Table 4, 40% fill for three or more wires.
CONDUIT_FILL_SQ_IN = {
    "PVC": (('1/2"', 0.114), ('3/4"', 0.203), ('1"', 0.333), ('1-1/4"', 0.581), ('1-1/2"', 0.794)),
    "EMT": (('1/2"', 0.122), ('3/4"', 0.213), ('1"', 0.346), ('1-1/4"', 0.598), ('1-1/2"', 0.814)),
}
SMALLEST_CONDUIT = '3/4"'


@dataclass(frozen=True)
class Circuit:
    load_amps: float
    required_amps: float
    breaker: int
    wire: Wire
    ground: str
    voltage_drop_volts: float
    voltage_drop_percent: float
    upsized_for_voltage_drop: bool


def size_breaker(required_amps: float) -> int:
    for breaker in STANDARD_BREAKERS:
        if breaker >= required_amps:
            return breaker
    raise ValueError(f"no standard breaker covers {required_amps:g} A")


def ground_size(breaker: int) -> str:
    return next(size for limit, size in GROUND_SIZES if breaker <= limit)


def voltage_drop(amps: float, one_way_ft: float, wire: Wire, volts: int = 240) -> tuple[float, float]:
    drop = 2 * COPPER_K * amps * one_way_ft / wire.circular_mils
    return drop, drop / volts * 100


def size_circuit(load_amps: float, one_way_ft: float, *, continuous: bool, volts: int = 240) -> Circuit:
    required = load_amps * (CONTINUOUS_FACTOR if continuous else 1)
    breaker = size_breaker(required)
    candidates = [wire for wire in WIRES if wire.ampacity_75c >= breaker]
    if not candidates:
        raise ValueError(f"no listed wire size carries {breaker} A")
    smallest = candidates[0]
    wire = next(
        (w for w in candidates
         if voltage_drop(load_amps, one_way_ft, w, volts)[1] <= MAX_VOLTAGE_DROP_PERCENT),
        candidates[-1],
    )
    drop, percent = voltage_drop(load_amps, one_way_ft, wire, volts)
    return Circuit(
        load_amps=load_amps,
        required_amps=required,
        breaker=breaker,
        wire=wire,
        ground=ground_size(breaker),
        voltage_drop_volts=drop,
        voltage_drop_percent=percent,
        upsized_for_voltage_drop=wire is not smallest,
    )


def conduit_size(circuit: Circuit, conduit_type: str, *, hots: int = 2) -> str:
    ground = next(w for w in WIRES if w.size == circuit.ground)
    fill = hots * circuit.wire.area_sq_in + ground.area_sq_in
    sizes = CONDUIT_FILL_SQ_IN[conduit_type]
    floor = next(i for i, (size, _) in enumerate(sizes) if size == SMALLEST_CONDUIT)
    for size, capacity in sizes[floor:]:
        if fill <= capacity:
            return size
    raise ValueError(f"{fill:.3f} sq in is too much wire for {conduit_type} up to {sizes[-1][0]}")
