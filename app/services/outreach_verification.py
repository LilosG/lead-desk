from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import requests
from bs4 import BeautifulSoup


USER_AGENT = "LILOsGrowth-LeadDesk/1.0 (+https://lilosgrowth.com)"


@dataclass(frozen=True)
class VerifiedClaim:
    signal: str | None
    text: str | None
    status: str
    note: str


class OutreachClaimVerifier:
    """Conservative verifier for claims that are safe to re-check live.

    Unsupported or ambiguous signals intentionally fall back to no technical
    claim. A missed claim is preferable to a false assertion in cold outreach.
    """

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def verify(self, context: dict[str, Any]) -> VerifiedClaim:
        if context.get("needs_manual_check"):
            return VerifiedClaim(
                signal=None,
                text=None,
                status="not_required",
                note="Manual-check prospect: generated without an audit claim.",
            )

        findings = context.get("findings") or []
        website_url = context.get("resolved_url") or context.get("website_url")

        for finding in findings:
            signal = finding.get("signal")
            if signal == "no_website" and not context.get("website_url"):
                return VerifiedClaim(
                    signal=signal,
                    text=(
                        "I noticed your Google listing does not currently point to a business website."
                    ),
                    status="verified",
                    note="Verified from the current business record: no website URL is present.",
                )

            if signal in {"no_localbusiness_schema", "no_title"} and website_url:
                live = self._fetch_page(website_url)
                if live is None:
                    continue
                final_url, html = live

                if signal == "no_localbusiness_schema":
                    schema_state = self._localbusiness_schema_state(html)
                    if schema_state == "absent":
                        return VerifiedClaim(
                            signal=signal,
                            text=(
                                "I noticed the homepage does not appear to include LocalBusiness schema markup."
                            ),
                            status="verified",
                            note=f"Re-checked live homepage before drafting: {final_url}",
                        )
                    if schema_state == "ambiguous":
                        continue

                if signal == "no_title" and not self._has_title(html):
                    return VerifiedClaim(
                        signal=signal,
                        text="I noticed the homepage is missing a usable HTML title tag.",
                        status="verified",
                        note=f"Re-checked live homepage before drafting: {final_url}",
                    )

        return VerifiedClaim(
            signal=None,
            text=None,
            status="not_required",
            note=(
                "No safely re-verifiable outreach claim was available; draft generated without a technical assertion."
            ),
        )

    def _fetch_page(self, url: str) -> tuple[str, str] | None:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=self.timeout_seconds,
                allow_redirects=True,
            )
        except requests.RequestException:
            return None

        # Never interpret access controls, WAFs, throttling, or server errors as
        # evidence of a missing website feature.
        if response.status_code >= 400:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "xhtml" not in content_type:
            return None
        return response.url, response.text

    @staticmethod
    def _has_title(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        return bool(soup.title and soup.title.get_text(strip=True))

    @staticmethod
    def _localbusiness_schema_state(
        html: str,
    ) -> Literal["present", "absent", "ambiguous"]:
        """Assess homepage JSON-LD without turning uncertainty into a claim."""
        local_types = {
            "LocalBusiness",
            "ProfessionalService",
            "HomeAndConstructionBusiness",
            "Electrician",
            "Plumber",
            "HVACBusiness",
            "RoofingContractor",
            "GeneralContractor",
            "HousePainter",
            "Locksmith",
            "MovingCompany",
            "AutoRepair",
            "AutoBodyShop",
            "Dentist",
            "LegalService",
            "RealEstateAgent",
            "MedicalBusiness",
            "HealthAndBeautyBusiness",
            "Store",
            "FoodEstablishment",
            "LodgingBusiness",
        }
        neutral_types = {
            "WebSite",
            "WebPage",
            "CollectionPage",
            "AboutPage",
            "ContactPage",
            "FAQPage",
            "ItemList",
            "BreadcrumbList",
            "Organization",
            "Corporation",
            "Person",
            "ImageObject",
            "VideoObject",
            "Article",
            "BlogPosting",
            "Product",
            "Offer",
            "Service",
            "SearchAction",
            "EntryPoint",
        }

        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        if not scripts:
            return "absent"

        saw_valid_payload = False
        saw_ambiguous = False

        for script in scripts:
            raw = script.string or script.get_text()
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                saw_ambiguous = True
                continue

            saw_valid_payload = True
            schema_types = OutreachClaimVerifier._collect_schema_types(payload)
            if schema_types & local_types:
                return "present"
            if schema_types - neutral_types:
                saw_ambiguous = True

        if saw_ambiguous:
            return "ambiguous"
        if saw_valid_payload:
            return "absent"
        return "ambiguous"

    @staticmethod
    def _collect_schema_types(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            raw_type = value.get("@type")
            if isinstance(raw_type, str):
                found.add(raw_type)
            elif isinstance(raw_type, list):
                found.update(item for item in raw_type if isinstance(item, str))
            for item in value.values():
                found.update(OutreachClaimVerifier._collect_schema_types(item))
        elif isinstance(value, list):
            for item in value:
                found.update(OutreachClaimVerifier._collect_schema_types(item))
        return found
