from __future__ import annotations


# Central outreach policy. Scoring may contain many useful internal signals,
# but cold outreach may only rely on findings that are explicitly approved here.
CLIENT_FACING_CLAIMS: dict[str, str] = {
    "no_website": "Your Google listing doesn't currently link to a business website.",
    "no_ssl": "The site is still loading over an unsecured HTTP connection instead of HTTPS.",
    "no_title": "The homepage doesn't currently have a usable page title for search engines.",
    "no_localbusiness_schema": (
        "The homepage isn't currently using structured business markup to identify the company to Google."
    ),
}

OUTREACHABLE_SIGNALS: tuple[str, ...] = tuple(CLIENT_FACING_CLAIMS)


def client_facing_claim(signal: str | None, verified_text: str | None) -> str | None:
    """Return approved recipient-facing wording for a verified signal.

    Unknown and internal-only signals are deliberately rejected. Adding a new
    scoring/verifier signal never makes it eligible for cold outreach until it is
    explicitly approved here.
    """
    if not signal or not verified_text:
        return None
    return CLIENT_FACING_CLAIMS.get(signal)
