from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecipientEvidence:
    """Public prospect facts that are safe to use in recipient-facing outreach.

    Internal LILOs scoring, tiers, percentiles, opportunity labels, and inferred
    business-age claims are intentionally excluded from this contract.
    """

    rating: float | None
    review_count: int
    last_review_days: int | None
    recent_reviews_90d: int | None
    confirmed_trading: bool
    established: bool

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "RecipientEvidence | None":
        if not row:
            return None

        raw_rating = row.get("rating")
        rating = float(raw_rating) if raw_rating is not None else None
        return cls(
            rating=rating,
            review_count=int(row.get("review_count") or 0),
            last_review_days=(
                int(row["last_review_days"])
                if row.get("last_review_days") is not None
                else None
            ),
            recent_reviews_90d=(
                int(row["recent_reviews_90d"])
                if row.get("recent_reviews_90d") is not None
                else None
            ),
            confirmed_trading=bool(row.get("confirmed_trading")),
            established=bool(row.get("established")),
        )


def recipient_context_sentence(
    business_name: str,
    evidence: RecipientEvidence | None,
) -> str | None:
    """Render only literal public facts; never expose internal qualification data."""

    if evidence is None:
        return None

    if (
        evidence.rating is not None
        and 0.0 <= evidence.rating <= 5.0
        and evidence.rating >= 4.0
        and evidence.review_count >= 10
    ):
        return (
            f"You already have a strong review profile at {evidence.rating:.1f} stars "
            f"across {evidence.review_count:,} reviews"
        )

    if evidence.review_count >= 20:
        return f"You already have {evidence.review_count:,} Google reviews"

    return None


def recipient_finding_block(
    *,
    business_name: str,
    technical_claim: str,
    evidence: RecipientEvidence | None,
) -> str:
    """Combine public business context with one separately verified technical claim."""

    context = recipient_context_sentence(business_name, evidence)
    if not context:
        return technical_claim

    technical = technical_claim.strip()
    if technical:
        technical = technical[0].lower() + technical[1:]
    return f"{context}, but {technical}"
