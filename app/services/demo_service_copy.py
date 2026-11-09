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

# Lines for niches outside the trades, checked before the trade lines when the
# demo knows its niche profile. Older templates don't pass a profile, so their
# output is unchanged.
_PROFILE_LINES: dict[str, list[tuple[str, str]]] = {
    "medical_aesthetic": [
        (r"botox|neurotox|dysport|xeomin|wrinkle", "Softens expression lines on the forehead, frown lines and around the eyes."),
        (r"filler|lip", "Restores volume and shape to lips, cheeks and under-eye areas."),
        (r"laser hair", "Longer-lasting hair reduction without the routine of shaving or waxing."),
        (r"hydrafacial|facial", "Deep cleansing and hydration for clearer, brighter skin."),
        (r"peel", "Refreshes tone and texture and fades sun damage and dark spots."),
        (r"microneedl|prp", "Encourages collagen to smooth texture, fine lines and acne scarring."),
        (r"laser|ipl|resurfac", "Targets sun damage, redness and uneven tone."),
        (r"body|sculpt|contour|coolsculpt", "Non-surgical options for stubborn areas that don't respond to diet and exercise."),
        (r"weight|semaglutide|tirzepatide", "Medically guided plans built around your goals and health history."),
        (r"iv|vitamin", "Hydration and nutrient support delivered in a short visit."),
    ],
    "dental": [
        (r"implant", "A permanent replacement for missing teeth that looks and works like your own."),
        (r"whiten", "A brighter smile from in-office or take-home whitening."),
        (r"invisalign|aligner|orthodont|braces", "Straighter teeth with clear aligners or braces, planned around your smile."),
        (r"cosmetic|veneer|bonding", "Veneers, bonding and other ways to change the look of your smile."),
        (r"clean|exam|hygien|check", "Routine cleanings and exams that catch small problems early."),
        (r"emergenc|urgent", "A cracked tooth, sudden pain or a lost filling. Call and explain what happened."),
        (r"crown|bridge", "Crowns and bridges that protect damaged teeth and fill gaps."),
        (r"root canal|endo", "Relief from a painful, infected tooth while saving the tooth itself."),
        (r"pediatric|kid|child", "Gentle care that helps kids feel comfortable at the dentist."),
        (r"general|family", "Everyday dental care for the whole family, from checkups to fillings."),
    ],
    "real_estate": [
        (r"first", "A clear walkthrough of the buying process for first-time buyers."),
        (r"buy", "From the first showing to closing day, with a plan for your price range and timing."),
        (r"sell|list", "Pricing, presentation and marketing that put your home in front of the right buyers."),
        (r"valu|apprais|worth", "Find out what your home could sell for in today's market."),
        (r"relocat", "Moving to the area? Get to know the neighborhoods before you commit."),
        (r"invest|rental", "Find properties that fit your rental or investment goals."),
        (r"luxury", "Discreet representation for high-end homes."),
    ],
    "legal": [
        (r"\bcar\b|auto|vehicle", "Injured in a crash? Understand your options before you talk to an insurer."),
        (r"truck|commercial vehicle", "Truck crashes involve more parties and more insurance. Get answers early."),
        (r"motorcycle", "Riders often face unfair assumptions after a crash. Know where you stand."),
        (r"slip|fall|premises", "Hurt on someone else's property? Find out whether you may have a claim."),
        (r"dog|bite|animal", "Medical bills and recovery after an animal attack, explained."),
        (r"wrongful death", "Guidance for families after losing someone to another's negligence."),
        (r"work|employ", "Hurt on the job? Learn what you may be owed and how to claim it."),
        (r"medical|malpractice", "When care goes wrong, find out whether you have a case."),
        (r"family|divorce|custody", "Clear guidance through divorce, custody and other family matters."),
        (r"estate|will|trust", "Wills, trusts and plans that protect the people you care about."),
        (r"criminal|dui|defense", "Know your rights and your options from the start."),
    ],
    "wellness_health": [
        (r"adjust|chiropract", "Hands-on adjustments to ease pain and help you move more freely."),
        (r"back", "Relief for lower and upper back pain, from stiffness to sharp flare-ups."),
        (r"neck|headache|migraine", "Care for neck pain, stiffness and tension headaches."),
        (r"sport", "Recover from sports injuries and get back to training."),
        (r"auto|accident|whiplash", "Assessment and care after a car accident, including whiplash."),
        (r"posture|ergonom", "Habits and care for better posture at work and at home."),
        (r"massage", "Therapeutic massage to relieve tension and support recovery."),
        (r"physical therapy|rehab", "Guided rehab to rebuild strength and mobility."),
        (r"acupunct", "Traditional acupuncture for pain, stress and overall wellbeing."),
    ],
    "auto": [
        (r"brake", "Squealing, grinding or a soft pedal. Have your brakes checked."),
        (r"oil", "Regular oil changes that keep your engine running clean."),
        (r"diagnos|check engine|engine", "Check-engine light on? Find out what's behind it."),
        (r"\bac\b|air cond", "Warm air from the vents? Get your AC cooling again."),
        (r"tire|alignment|wheel", "Tires, rotations and alignments for a smoother, safer ride."),
        (r"maintenance|service", "Factory-scheduled maintenance that keeps your vehicle reliable."),
        (r"transmission", "Slipping, hard shifts or delays when you put it in gear."),
        (r"battery|electrical|starter", "Trouble starting or electrical gremlins, tracked down."),
    ],
}

_FALLBACK_LINES = (
    "Tell us what you need and we'll talk through the best way to handle it.",
    "Not sure this is the right {unit}? Describe what's going on and ask.",
    "Share a few details about what you're looking for and go over your options.",
)


def describe_service(
    service: str, position: int = 0, unit: str = "service", profile: str | None = None
) -> str:
    """The card line for a service. `position` varies the fallback across a page."""
    name = service.lower()
    for pattern, line in _PROFILE_LINES.get(profile or "", []):
        if re.search(pattern, name):
            return line
    for pattern, line in _SERVICE_LINES:
        if re.search(pattern, name):
            return line
    return _FALLBACK_LINES[position % len(_FALLBACK_LINES)].format(unit=unit)
