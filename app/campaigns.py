"""The outreach campaigns, and what makes each one different.

Each campaign keeps its own stages and drafts. Opt-outs and the contact
cooldown are shared across all of them.
"""
from __future__ import annotations

from dataclasses import dataclass

SEO_WEBSITES = "seo_websites"
EV_PERMITS = "ev_permits"
DEFAULT_CAMPAIGN = SEO_WEBSITES
# One business shouldn't hear two different pitches within this many days.
COOLDOWN_DAYS = 30


@dataclass(frozen=True)
class Campaign:
    key: str
    claim_signal: str
    prep_label: str
    uses_audit: bool


CAMPAIGNS = {
    SEO_WEBSITES: Campaign(SEO_WEBSITES, "audit_report", "Audit + email + Gmail draft", True),
    EV_PERMITS: Campaign(EV_PERMITS, "ev_permit_offer", "Email + Gmail draft", False),
}


def get_campaign(key: str | None) -> Campaign:
    return CAMPAIGNS[key or DEFAULT_CAMPAIGN]


# What a site says when it offers EV charger installs. Keep in step with
# EV_SERVICE in pipeline/site_signals.py, which reads the full homepage.
EV_SERVICE_PATTERN = (
    r"\belectric\s+(vehicle|car)s?\b"
    r"|\b(evs?|tesla)\b.{0,30}(charg|install|outlet|ready|circuit|wiring)"
    r"|\bcharg.{0,30}\bevs?\b"
    r"|\b(car|vehicle)[\s-]+charg"
    r"|\bcharging\s+stations?\b"
    r"|\blevel[\s-]*2\s+(home\s+)?charg"
    r"|\bwall\s+connector\b"
    r"|\bevse\b"
)
# Postgres spells a word boundary \y rather than \b.
EV_SERVICE_SQL = EV_SERVICE_PATTERN.replace(r"\b", r"\y")

@dataclass(frozen=True)
class PermitJob:
    slug: str
    label: str
    regex: str


# The four job types the Permit Packets campaign covers, in the order they are
# listed everywhere. A site "shows" a job when its text, menu or URLs match.
# Keep in step with PERMIT_JOB_PATTERNS in pipeline/site_signals.py.
# Wording is deliberately narrow: "day spa" or "spa treatments" are not a hot
# tub install, and a bare "panel" is not a panel upgrade.
PERMIT_JOBS: tuple[PermitJob, ...] = (
    PermitJob("ev_charger", "EV", EV_SERVICE_PATTERN),
    PermitJob(
        "service_upgrade", "Panel upgrades",
        r"(?<!solar\s)\b(breaker\s+box|(electrical\s+|breaker\s+)?panel)s?\s+(upgrad|replac|chang)\w*"
        r"|\bservice\s+(upgrad|chang)\w*"
        r"|\b(100|125|150|200|400)[\s-]*amps?\s+(electrical\s+)?(service|panel)"
    ),
    PermitJob(
        "subpanel", "Subpanels",
        r"\bsub[\s-]?panels?\b"
        r"|\bdetached\s+(garage|building|workshop)s?\b.{0,40}(power|wiring|feeder|electric)"
        r"|\b(power|wiring|feeder|electric)\w*\b.{0,40}\bdetached\s+(garage|building|workshop)"
        r"|\badus?\b.{0,40}(electric|wiring|panel)"
        r"|\b(electric|wiring|panel)\w*\b.{0,40}\badus?\b"
    ),
    PermitJob(
        "appliance_circuit", "240 V circuits",
        r"\b(hot\s*tub|spa|jacuzzi|swim\s+spa)s?\b.{0,40}(wiring|install|circuit|power)"
        r"|\b(wiring|install|circuit|power)\w*\b.{0,40}\b(hot\s*tub|spa|jacuzzi|swim\s+spa)s?\b"
        r"|\bsaunas?\b"
        r"|\bheat\s+pumps?\b.{0,40}(wiring|circuit|install)"
        r"|\b(wiring|circuit|install)\w*\b.{0,40}\bheat\s+pumps?\b"
        r"|\bmini[\s-]*splits?\b"
        r"|\b(240|220)[\s-]*(v|volts?)\b[\s-]*(circuit|outlet|line)"
    ),
)
PERMIT_JOB_SLUGS = tuple(job.slug for job in PERMIT_JOBS)
PERMIT_JOB_LABELS = {job.slug: job.label for job in PERMIT_JOBS}
# Any one of the four. Postgres spells a word boundary \y.
PERMIT_JOBS_PATTERN = "|".join(job.regex for job in PERMIT_JOBS)
PERMIT_JOBS_SQL = PERMIT_JOBS_PATTERN.replace(r"\b", r"\y")

# City permit requirements, from each city's published EV checklist. "full"
# cities ask for a real packet. "simple" cities use a no-plan permit for EV
# chargers, so the EV line makes no city claim there. These are EV-only: no
# other job type gets a city-specific claim.
EV_PERMIT_CITIES: dict[tuple[str, str], dict[str, str]] = {
    ("Oro Valley", "AZ"): {
        "fit": "full",
        "asks_for": "a site plan, one-line diagram and load calculation",
        "source": "https://www.orovalleyaz.gov/files/assets/public/v/1/documents/"
                  "community-and-economic-development/permitting-division/electric-car-charging-stations.pdf",
    },
    ("El Cajon", "CA"): {
        "fit": "full",
        "asks_for": "a scaled site plan, load calculation and, on larger chargers, a single-line diagram",
        "source": "https://elcajon.gov/home/showpublisheddocument/26307/637914284204530000",
    },
    ("Brea", "CA"): {
        "fit": "full",
        "asks_for": "a site plan, load calculation and single-line diagram",
        "source": "https://www.cityofbrea.gov/1782/EV-Charger-Checklist---Residential",
    },
    ("Escondido", "CA"): {
        "fit": "full",
        "asks_for": "a site or floor plan, load calculation and single-line diagram",
        "source": "https://www.escondido.org/Data/Sites/1/media/pdfs/Building/InfoGuideline30.pdf",
    },
    ("Moreno Valley", "CA"): {
        "fit": "full",
        "asks_for": "a scaled site plan, load calculation and single-line diagram",
        "source": "https://www.moval.org/city_hall/forms/building-safety/ResidentialEVCSExpeditedChecklist.pdf",
    },
    ("Vista", "CA"): {
        "fit": "full",
        "asks_for": "a key plan and a signed load calculation",
        "source": "https://vista.gov/home/showpublisheddocument/13375/638566251365800000",
    },
    ("Irvine", "CA"): {
        "fit": "full",
        "asks_for": "a load worksheet and single-line diagram",
        "source": "https://cityofirvine.gov/node/69646",
    },
    ("Murrieta", "CA"): {
        "fit": "simple",
        "source": "https://www.murrietaca.gov/DocumentCenter/View/12125/DS-149-Residential-Electrical-Vehicle-Charger-Guidelines",
    },
    ("Chino", "CA"): {
        "fit": "simple",
        "source": "https://www.cityofchino.org/DocumentCenter/View/7290/Residential-EV-Charger-Checklist-PDF",
    },
    ("San Diego", "CA"): {
        "fit": "simple",
        "source": "https://www.sandiego.gov/development-services/forms-publications/information-bulletins/187",
    },
    ("Frisco", "TX"): {
        "fit": "simple",
        "source": "https://www.friscotexas.gov/DocumentCenter/View/39322",
    },
}


def simple_permit_cities() -> list[str]:
    return [f"{city}, {state}" for (city, state), info in EV_PERMIT_CITIES.items()
            if info["fit"] == "simple"]


def permit_city(city: str | None, state: str | None) -> dict[str, str] | None:
    return EV_PERMIT_CITIES.get(((city or "").strip(), (state or "").strip().upper()))
