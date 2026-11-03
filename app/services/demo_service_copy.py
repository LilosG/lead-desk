"""One plain line for each service card on a demo site.

Each line describes the job and the problem that brings a customer to it. None
of them state anything about the business itself, such as speed, price,
guarantees or availability, because a demo can only know what's on its listing.
"""
from __future__ import annotations

import re

# First match wins, so specific jobs sit above the general ones.
_SERVICE_LINES: list[tuple[str, str]] = [
    (r"commercial", "Upkeep and repairs for offices, shops and rental properties, planned around your business."),
    (r"emergenc|urgent", "When it can't wait, call and explain what's happening so you know what to do next."),
    (r"water heater|tankless", "No hot water, a leaking tank or an aging unit. Compare repairing it with replacing it."),
    (r"sewer", "Backups, slow drains throughout the house or sewer smells point to the main line."),
    (r"leak", "A damp wall, a rising water bill or a drip you can't place. Find the source first."),
    (r"drain|clog", "Slow sinks, standing water or a stubborn clog that keeps coming back."),
    (r"repipe|re-pipe|pipe", "Low pressure, discolored water or aging pipes that keep springing leaks."),
    (r"fixture|faucet|toilet|sink|shower", "Faucets, toilets, sinks and showers repaired, replaced or newly installed."),
    (r"panel|breaker", "Tripping breakers or an older panel that can't keep up with what your home uses."),
    (r"ev\b|charger", "A home charging setup matched to your vehicle, your panel and where you park."),
    (r"generator", "Backup power sized for what you need to keep running during an outage."),
    (r"rewir|wiring", "Older wiring, flickering lights or new circuits for an addition or remodel."),
    (r"light", "New fixtures, recessed lighting and outdoor lights, indoors or out."),
    (r"outlet|switch", "Dead outlets, worn switches or more power exactly where you need it."),
    (r"\bac\b|air condition|cooling", "Weak airflow, warm air or a system that won't keep the house comfortable."),
    (r"furnace|heating|heat pump", "No heat, uneven rooms or a system that's getting noisy and expensive to run."),
    (r"duct", "Dusty rooms, weak vents or uneven temperatures from one room to the next."),
    (r"roof", "Missing shingles, ceiling stains or storm damage looked at before it spreads."),
    (r"gutter", "Overflowing or sagging gutters that send water where it shouldn't go."),
    (r"paint", "Interior and exterior painting, from one room to the whole property."),
    (r"remodel|renovat", "Kitchens, bathrooms and other rooms planned around how you use the space."),
    (r"garage door", "Doors that stick, broken springs or an opener that has stopped responding."),
    (r"fenc", "New fencing or repairs for privacy, security or a better-looking yard."),
    (r"concrete|hardscape|paver", "Driveways, patios and walkways built or repaired to last."),
    (r"landscap|lawn|irrigation|sprinkler", "Planting, irrigation and upkeep for a yard that stays in good shape."),
    (r"tree", "Trimming, removal and cleanup for trees that have become a problem."),
    (r"clean", "Regular or one-time cleaning, set up around your schedule."),
    (r"pest|termite", "Ants, rodents or termites identified and dealt with at the source."),
    (r"lock", "Lockouts, rekeying and new locks for your home, business or vehicle."),
    (r"pool", "Cleaning, repairs and equipment for a pool that's ready when you are."),
    (r"maintenance|tune", "Routine upkeep that catches small problems before they turn into big ones."),
    (r"repair", "Something stopped working? Describe the problem and talk through the options."),
    (r"install|replace", "Planning something new? Talk through what fits your property and budget."),
]

_FALLBACK_LINES = (
    "Tell us what you need and we'll talk through the best way to handle it.",
    "Not sure this is the right {unit}? Describe what's going on and ask.",
    "Share a few details about what you're looking for and go over your options.",
)


def describe_service(service: str, position: int = 0, unit: str = "service") -> str:
    """The card line for a service. `position` varies the fallback across a page."""
    name = service.lower()
    for pattern, line in _SERVICE_LINES:
        if re.search(pattern, name):
            return line
    return _FALLBACK_LINES[position % len(_FALLBACK_LINES)].format(unit=unit)
