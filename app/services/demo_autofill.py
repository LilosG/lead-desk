"""Pre-fills the demo builder so a mockup can be made without typing.

Services: the business's own site menu first, then a short starter list of the
core offerings for its niche, up to six cards. Service areas: the business's own
town, then nearby towns from businesses already swept, nearest first. Nothing
here calls Google or any paid API.
"""
from __future__ import annotations

import re

from pipeline import verticals as vertical_config

MAX_SERVICES = 6
MAX_AREAS = 8

# Core offerings nearly every business in the niche provides. Keyed by sweep
# vertical first, then by niche profile for custom niches.
STARTER_SERVICES: dict[str, list[str]] = {
    "electrician": ["Panel Upgrades", "EV Charger Installation", "Lighting Installation",
                    "Electrical Repairs", "Rewiring", "Generator Installation"],
    "plumber": ["Drain Cleaning", "Water Heater Services", "Leak Detection",
                "Fixture Installation", "Repiping", "Sewer Line Repair"],
    "hvac": ["AC Repair", "AC Installation", "Furnace Repair",
             "Heat Pumps", "Seasonal Tune-Ups", "Duct Cleaning"],
    "roofing": ["Roof Repair", "Roof Replacement", "Roof Inspections",
                "Storm Damage Repair", "Leak Repair", "Gutters"],
    "restoration": ["Water Damage Restoration", "Fire & Smoke Damage", "Mold Remediation",
                    "Storm Damage", "Sewage Cleanup", "Emergency Water Extraction"],
    "landscaping": ["Landscape Design", "Lawn Care", "Irrigation",
                    "Hardscaping", "Tree & Shrub Care", "Yard Cleanups"],
    "handyman": ["Home Repairs", "Drywall Repair", "Painting",
                 "Fixture Installation", "Door & Window Repair", "Furniture Assembly"],
    "party_rentals": ["Tables & Chairs", "Tents & Canopies", "Bounce Houses",
                      "Linens", "Event Lighting", "Delivery & Setup"],
    "real_estate_agent": ["Buying a Home", "Selling a Home", "Home Valuations",
                          "First-Time Buyers", "Relocation", "Investment Properties"],
    "med_spa": ["Botox & Neurotoxins", "Dermal Fillers", "Laser Hair Removal",
                "Facials", "Chemical Peels", "Microneedling"],
    "dentist": ["General Dentistry", "Cleanings & Exams", "Cosmetic Dentistry",
                "Teeth Whitening", "Dental Implants", "Emergency Dental Care"],
    "chiropractor": ["Chiropractic Adjustments", "Back Pain", "Neck Pain",
                     "Sports Injuries", "Auto Injury Care", "Posture Care"],
    "personal_injury_attorney": ["Car Accidents", "Truck Accidents", "Motorcycle Accidents",
                                 "Slip & Fall", "Dog Bites", "Wrongful Death"],
    "auto_repair": ["Brake Repair", "Oil Changes", "Engine Diagnostics",
                    "AC Repair", "Tires & Alignment", "Scheduled Maintenance"],
}
PROFILE_STARTERS = {
    "medical_aesthetic": "med_spa",
    "dental": "dentist",
    "real_estate": "real_estate_agent",
    "wellness_health": "chiropractor",
    "legal": "personal_injury_attorney",
    "auto": "auto_repair",
}


# Words that say what kind of job it is rather than what it's for, so they
# don't count when checking whether a starter repeats a service already listed.
_GENERIC_WORDS = {
    "repair", "installation", "install", "service", "services", "replacement", "care",
    "emergency", "residential", "commercial", "home", "general", "inspection",
    "maintenance", "upgrade", "cleaning", "damage", "restoration",
}


def _key_words(name: str) -> set[str]:
    words = re.findall(r"[a-z]+", name.lower())
    return {
        w.rstrip("s") for w in words
        if len(w) > 2 and w not in _GENERIC_WORDS and w.rstrip("s") not in _GENERIC_WORDS
    }


def _overlaps(words: set[str], taken: set[str]) -> bool:
    """True when a starter names something already listed ("Facials" vs "HydraFacial")."""
    return any(w == t or (len(w) >= 5 and w in t) or (len(t) >= 5 and t in w) for w in words for t in taken)


def starter_services(vertical: str | None) -> list[str]:
    raw = (vertical or "").strip()
    if not raw:
        return []
    try:
        key = vertical_config.normalize_vertical_key(raw)
    except ValueError:
        key = ""
    if key in STARTER_SERVICES:
        return list(STARTER_SERVICES[key])
    profile = vertical_config.vertical_profile(raw)
    # Generic and home-service custom niches have no safe default list.
    starter_key = PROFILE_STARTERS.get(profile)
    return list(STARTER_SERVICES[starter_key]) if starter_key else []


def suggested_services(site_services: list[str], vertical: str | None) -> list[str]:
    """The business's own services, topped up with niche starters to six."""
    result = [s for s in site_services if s][:MAX_SERVICES]
    starters = starter_services(vertical)
    # Words shared by several starters ("roof", "dentistry") name the niche, not
    # a service, so they can't mark a starter as already covered.
    counts: dict[str, int] = {}
    for starter in starters:
        for word in _key_words(starter):
            counts[word] = counts.get(word, 0) + 1
    niche_words = {word for word, count in counts.items() if count > 1}
    taken = set().union(*(_key_words(s) for s in result)) - niche_words if result else set()
    for starter in starters:
        if len(result) >= MAX_SERVICES:
            break
        words = _key_words(starter) - niche_words
        if starter.lower() in {s.lower() for s in result} or _overlaps(words, taken):
            continue
        result.append(starter)
        taken |= words
    return result


def suggested_areas(own_cities: list[str], nearby: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for town in [*own_cities, *nearby]:
        clean = " ".join(str(town or "").split())
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        result.append(clean)
        if len(result) >= MAX_AREAS:
            break
    return result
