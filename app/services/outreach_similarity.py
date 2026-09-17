from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Iterable


FOOTER_MARKER = "\n\nMike\nLILOs Growth\n"
DEFAULT_SIMILARITY_THRESHOLD = 0.80


def normalize_outreach_note(
    body: str,
    *,
    business_name: str | None,
    verified_claim: str | None,
) -> str:
    """Normalize recipient-specific facts away so rhetorical structure can be compared."""

    note = (body or "").split(FOOTER_MARKER, 1)[0].strip().lower()
    if verified_claim:
        note = note.replace(verified_claim.strip().lower(), " [finding] ")
    note = note.replace("[[verified_finding]]", " [finding] ")
    if business_name:
        note = note.replace(business_name.strip().lower(), " [business] ")

    # Public Google evidence is useful recipient personalization, but it must not
    # lower the measured similarity of otherwise identical email structures.
    note = re.sub(
        r"google shows\s+\[business\]\s+at\s+\d(?:\.\d+)?\s+stars\s+across\s+[\d,]+\s+reviews\.?",
        " [public_evidence] ",
        note,
    )
    note = re.sub(
        r"google shows\s+[\d,]+\s+reviews\s+for\s+\[business\]\.?",
        " [public_evidence] ",
        note,
    )

    note = re.sub(r"[^a-z0-9\[\]_']+", " ", note)
    note = re.sub(r"\s+", " ", note).strip()
    return note


def structural_similarity(
    candidate_body: str,
    *,
    candidate_business_name: str | None,
    candidate_verified_claim: str | None,
    existing_body: str,
    existing_business_name: str | None,
    existing_verified_claim: str | None,
) -> float:
    candidate = normalize_outreach_note(
        candidate_body,
        business_name=candidate_business_name,
        verified_claim=candidate_verified_claim,
    )
    existing = normalize_outreach_note(
        existing_body,
        business_name=existing_business_name,
        verified_claim=existing_verified_claim,
    )
    if not candidate or not existing:
        return 0.0

    # difflib.SequenceMatcher can produce slightly different ratios when the same
    # two strings are supplied in reverse order. Diversity enforcement must be
    # order-independent, otherwise a draft can pass during admission and fail in
    # the final pairwise audit. Use the stricter of both directions.
    forward = SequenceMatcher(None, candidate, existing, autojunk=False).ratio()
    reverse = SequenceMatcher(None, existing, candidate, autojunk=False).ratio()
    return max(forward, reverse)


def most_similar_recent_draft(
    candidate_body: str,
    *,
    candidate_business_name: str | None,
    candidate_verified_claim: str | None,
    recent_drafts: Iterable[tuple[str | None, str, str | None]],
) -> tuple[float, str | None]:
    """Return the highest structural similarity and matching business name.

    recent_drafts entries are (business_name, body, verified_claim). The comparison
    intentionally ignores recipient-specific names/findings and measures the
    rhetorical skeleton instead.
    """

    best_ratio = 0.0
    best_name: str | None = None
    for business_name, body, verified_claim in recent_drafts:
        ratio = structural_similarity(
            candidate_body,
            candidate_business_name=candidate_business_name,
            candidate_verified_claim=candidate_verified_claim,
            existing_body=body,
            existing_business_name=business_name,
            existing_verified_claim=verified_claim,
        )
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = business_name
    return best_ratio, best_name


def is_too_similar(
    candidate_body: str,
    *,
    candidate_business_name: str | None,
    candidate_verified_claim: str | None,
    recent_drafts: Iterable[tuple[str | None, str, str | None]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[bool, float, str | None]:
    ratio, business_name = most_similar_recent_draft(
        candidate_body,
        candidate_business_name=candidate_business_name,
        candidate_verified_claim=candidate_verified_claim,
        recent_drafts=recent_drafts,
    )
    return ratio >= threshold, ratio, business_name
