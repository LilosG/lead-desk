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
EV_SERVICE_SQL = (
    r"\m(ev|evs|electric vehicles?|tesla)\M.{0,30}charg"
    r"|charg.{0,30}\m(ev|evs|electric vehicles?)\M"
    r"|\mevse\M"
)

# City permit requirements, from each city's published EV checklist. "full"
# cities ask for a real packet. "simple" cities use a no-plan permit, so the
# offer has little to save them and those leads stay out of the campaign.
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
