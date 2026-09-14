from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

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

                if signal == "no_localbusiness_schema" and not self._has_localbusiness_schema(html):
                    return VerifiedClaim(
                        signal=signal,
                        text=(
                            "I noticed the homepage does not appear to include LocalBusiness schema markup."
                        ),
                        status="verified",
                        note=f"Re-checked live homepage before drafting: {final_url}",
                    )

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
    def _has_localbusiness_schema(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if OutreachClaimVerifier._contains_localbusiness_type(payload):
                return True
        return False

    @staticmethod
    def _contains_localbusiness_type(value: Any) -> bool:
        local_types = {
            "LocalBusiness",
            "ProfessionalService",
            "HomeAndConstructionBusiness",
            "Electrician",
            "Plumber",
            "HVACBusiness",
            "RoofingContractor",
            "GeneralContractor",
        }
        if isinstance(value, dict):
            raw_type = value.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(item in local_types for item in types):
                return True
            return any(
                OutreachClaimVerifier._contains_localbusiness_type(item)
                for item in value.values()
            )
        if isinstance(value, list):
            return any(
                OutreachClaimVerifier._contains_localbusiness_type(item)
                for item in value
            )
        return False
