from __future__ import annotations


# The verifier owns whether a claim is safe to make. This layer owns how that
# verified fact is expressed to a business owner. Keep technical verification
# details in the internal note; first-touch copy should use normal language.
CLIENT_FACING_CLAIMS = {
    "no_website": (
        "Your Google listing doesn't currently link to a business website."
    ),
    "no_ssl": (
        "The site is still loading over an unsecured HTTP connection instead of HTTPS."
    ),
    "no_title": (
        "The homepage doesn't currently have a usable page title for search engines."
    ),
    "no_localbusiness_schema": (
        "The homepage isn't currently using structured business markup to identify the company to Google."
    ),
    "template_builder": None,
}


def client_facing_claim(signal: str | None, verified_text: str | None) -> str | None:
    """Render a verified finding for first-touch outreach.

    A missing mapping falls back to the verifier text so adding a new verified
    signal does not silently discard it. Signals explicitly mapped to None are
    intentionally withheld from outreach even though they may remain useful
    internally for scoring or review.
    """
    if not signal or not verified_text:
        return None
    if signal in CLIENT_FACING_CLAIMS:
        return CLIENT_FACING_CLAIMS[signal]
    return verified_text
