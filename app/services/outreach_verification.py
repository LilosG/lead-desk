from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 2_000_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class VerifiedClaim:
    signal: str | None
    text: str | None
    status: str
    note: str


class OutreachClaimVerifier:
    """Re-check cold-outreach claims against current, live evidence.

    This deliberately has a higher evidence bar than scoring. The pipeline can
    rank on noisy signals; outbound copy must not state them as facts unless a
    current re-check can establish them safely. Uncertainty always becomes a
    claim-free draft.
    """

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def verify(self, context: dict[str, Any]) -> VerifiedClaim:
        if context.get("needs_manual_check"):
            return self._no_claim(
                "Manual-check prospect: generated without an audit claim."
            )

        findings = context.get("findings") or []
        website_url = context.get("resolved_url") or context.get("website_url")

        # A missing website is the only negative claim that can be established
        # directly from the current business record without fetching a site.
        for finding in findings:
            if finding.get("signal") == "no_website" and not context.get("website_url"):
                return VerifiedClaim(
                    signal="no_website",
                    text=(
                        "I noticed your Google listing does not currently point to a business website."
                    ),
                    status="verified",
                    note="Verified from the current business record: no website URL is present.",
                )

        if not website_url:
            return self._no_claim("No current website URL was available for live verification.")

        live = self._fetch_page(website_url)
        if live is None:
            # WAFs, access controls, throttling, 5xx responses, DNS failures,
            # timeouts, and crawler blocks are not evidence that the business
            # site is down or missing a feature.
            return self._no_claim(
                "Live site could not be verified safely; no technical claim was used."
            )

        final_url, html = live
        signals = [finding.get("signal") for finding in findings]

        for signal in signals:
            if signal == "no_ssl" and not final_url.lower().startswith("https://"):
                return VerifiedClaim(
                    signal=signal,
                    text="I noticed the site is still resolving over HTTP rather than HTTPS.",
                    status="verified",
                    note=f"Re-checked live final URL before drafting: {final_url}",
                )

            if signal == "no_title" and not self._has_title(html):
                return VerifiedClaim(
                    signal=signal,
                    text="I noticed the homepage is missing a usable HTML title tag.",
                    status="verified",
                    note=f"Re-checked live homepage before drafting: {final_url}",
                )

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

            if signal == "template_builder":
                builder = self._template_builder(html)
                if builder:
                    return VerifiedClaim(
                        signal=signal,
                        text=f"I noticed the site appears to be running on {builder}.",
                        status="verified",
                        note=f"Verified live builder signatures on: {final_url}",
                    )

        # Intentionally not asserted automatically:
        # - site_down: a failed request is not proof of downtime;
        # - nap_mismatch/no_photos/few_photos: source contract marks unsafe;
        # - no_contact_form/thin_content: static HTML absence is not enough to
        #   disprove JS-rendered content at cold-outreach evidence standards.
        return self._no_claim(
            "No safely re-verifiable outreach claim was available; draft generated without a technical assertion."
        )

    @staticmethod
    def _no_claim(note: str) -> VerifiedClaim:
        return VerifiedClaim(
            signal=None,
            text=None,
            status="not_required",
            note=note,
        )

    def _fetch_page(self, url: str) -> tuple[str, str] | None:
        """Fetch HTML conservatively and refuse private/internal destinations.

        Prospect URLs originate outside the application trust boundary. Every
        initial URL and redirect is validated before a request so live claim
        verification cannot be used as an SSRF path into localhost, metadata
        services, RFC1918 networks, or other non-public addresses.
        """
        current = url
        session = requests.Session()

        for _ in range(MAX_REDIRECTS + 1):
            if not self._is_public_http_url(current):
                return None
            try:
                response = session.get(
                    current,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    timeout=self.timeout_seconds,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException:
                return None

            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                response.close()
                if not location:
                    return None
                current = urljoin(current, location)
                continue

            # Never treat access controls, WAFs, throttling, or server errors as
            # evidence for a missing feature or downtime claim.
            if response.status_code >= 400:
                response.close()
                return None

            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type and "xhtml" not in content_type:
                response.close()
                return None

            body = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > MAX_HTML_BYTES:
                        response.close()
                        return None
            except requests.RequestException:
                response.close()
                return None
            encoding = response.encoding or "utf-8"
            final_url = response.url
            response.close()
            try:
                html = bytes(body).decode(encoding, errors="replace")
            except LookupError:
                html = bytes(body).decode("utf-8", errors="replace")
            return final_url, html

        return None

    @staticmethod
    def _is_public_http_url(url: str) -> bool:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        if not parsed.hostname or parsed.username or parsed.password:
            return False
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError:
            return False

        try:
            addresses = socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except (socket.gaierror, OSError):
            return False
        if not addresses:
            return False

        for address in addresses:
            try:
                ip = ipaddress.ip_address(address[4][0])
            except ValueError:
                return False
            if not ip.is_global:
                return False
        return True

    @staticmethod
    def _has_title(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        return bool(soup.title and soup.title.get_text(strip=True))

    @staticmethod
    def _template_builder(html: str) -> str | None:
        low = html.lower()
        signatures = (
            ("Wix", ("wixstatic.com", "wix-code", "wixsite.com")),
            ("Squarespace", ("static1.squarespace.com", "squarespace.com/static")),
            ("GoDaddy Website Builder", ("godaddysites.com", "wsimg.com")),
            ("Duda", ("duda.co", "dudaone.com", "dmcdn.net")),
            ("Weebly", ("weebly.com", "editmysite.com")),
        )
        for label, tokens in signatures:
            if any(token in low for token in tokens):
                return label
        return None

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
