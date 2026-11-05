"""What the Outreach page shows: each prospect's stage, and the next thing to do."""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Any, Literal

from app.campaigns import CAMPAIGNS, EV_PERMITS, get_campaign
from app.integrations.gmail import GmailDraftClient, GmailDraftError
from app.repositories.outreach_board import OutreachBoardRepository
from app.repositories.outreach_gmail import OutreachGmailRepository
from app.services.outreach import OutreachIntegrationUnavailable

Stage = Literal[
    "to_prep", "verify", "call", "review", "attention",
    "in_gmail", "contacted", "replied", "closed",
]
STAGES: tuple[str, ...] = (
    "to_prep", "verify", "call", "review", "attention",
    "in_gmail", "contacted", "replied", "closed",
)
FOLLOW_UP_AFTER_DAYS = 5


def days_since(value: datetime | None, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    return ((now or datetime.now(timezone.utc)) - value).days


def cooldown_note(row: dict[str, Any]) -> str | None:
    until = row.get("cooldown_until")
    if not until or row.get("stage") not in {"to_prep", "review", "attention"}:
        return None
    return f"Already in {row.get('cooldown_campaign')} outreach. Wait until {until:%b} {until.day}"


def lead_note(row: dict[str, Any], campaign: str) -> str | None:
    """Why this lead sits where it does in this campaign's list."""
    if campaign == EV_PERMITS:
        proof = "EV page" if row.get("ev_strength") == "page" else "Mentions EV work"
        brands = row.get("ev_brands") or []
        parts = [proof, *brands[:2], f"{row['review_count']} reviews" if row.get("review_count") else None]
        return " · ".join(p for p in parts if p)
    if row.get("ev_eligible") and row.get("stage") == "to_prep":
        return "Shows EV work: pitch EV Permits first"
    return None


def next_step(row: dict[str, Any], now: datetime | None = None) -> str:
    """One plain instruction for this prospect."""
    stage = row.get("stage")
    waiting = cooldown_note(row)
    if waiting:
        return waiting
    if stage == "to_prep":
        if not get_campaign(row.get("campaign_key")).uses_audit:
            return "Draft the email"
        return "Build the audit and draft the email"
    if stage == "verify":
        return "Open the site, then mark it checked or add an email"
    if stage == "call":
        return "Call them, or add an email to move them to email"
    if stage == "review":
        if not row.get("has_draft", bool(row.get("body"))):
            return "Generate the email draft"
        return "Read the draft, then create the Gmail draft"
    if stage == "attention":
        if row.get("status") == "no_outreach_finding":
            return "Nothing verified to write about. Rebuild the audit or archive"
        return row.get("verification_note") or "The claim failed verification. Regenerate the draft"
    if stage == "in_gmail":
        return "Review and send it from Gmail"
    if stage == "contacted":
        waited = days_since(row.get("contacted_at"), now)
        if waited is not None and waited >= FOLLOW_UP_AFTER_DAYS:
            return f"Follow up: no reply logged for {waited} days"
        return "Waiting for a reply"
    if stage == "replied":
        return "Reply in Gmail"
    return "Closed"


def gmail_block_reason(item: dict[str, Any], *, gmail_connected: bool) -> str | None:
    """Why Create Gmail draft can't run yet. None means it can."""
    if not gmail_connected:
        return "Gmail isn't connected. Connect it in Settings."
    if item.get("channel") != "email":
        return "This is a phone lead. Add an email on the prospect page to draft one."
    if item.get("gmail_draft_id"):
        return "A Gmail draft already exists for this prospect."
    if item.get("gmail_draft_pending"):
        return "A Gmail draft is still being confirmed. Refresh in a moment."
    if item.get("suppressed"):
        return "This address is on the do-not-contact list."
    if not (item.get("to_address") or "").strip():
        return "Add a recipient address first."
    if not item.get("subject") or not item.get("body"):
        return "There's no draft yet. Click Generate draft first."
    if item.get("verification_status") not in {"verified", "not_required"}:
        return "The claim in this draft failed verification. Regenerate the draft."
    campaign = get_campaign(item.get("campaign_key"))
    if item.get("claim_signal") != campaign.claim_signal:
        if campaign.uses_audit:
            return "This draft has no audit behind it. Click Regenerate draft to build one and attach it."
        return "Click Regenerate draft to write this campaign's email."
    return cooldown_note(item)


class OutreachBoardService:
    def __init__(
        self,
        repository: OutreachBoardRepository,
        *,
        gmail_repository: OutreachGmailRepository,
        gmail: GmailDraftClient | None,
    ) -> None:
        self.repository = repository
        self.gmail_repository = gmail_repository
        self.gmail = gmail

    def board(self, *, stage: str, page: int, page_size: int, campaign: str, **filters: Any) -> dict[str, Any]:
        if not get_campaign(campaign).uses_audit:
            # "Qualified" is the SEO score. A campaign without an audit doesn't use it.
            filters["qualified_only"] = False
        data = self.repository.board(
            campaign=campaign, stage=stage, page=page, page_size=page_size, **filters,
        )
        counts = {name: int(data["counts"].get(name, 0)) for name in STAGES}
        total = counts.get(stage, 0)
        return {
            "stage": stage,
            "counts": counts,
            "items": [{**row, "next_step": next_step({**row, "campaign_key": campaign}),
                       "lead_note": lead_note(row, campaign)}
                      for row in data["rows"]],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": ceil(total / page_size) if total else 0,
            },
            "filters": {"verticals": data["verticals"], "markets": data["markets"]},
        }

    def campaigns(self) -> list[dict[str, Any]]:
        known = [row for row in self.repository.campaigns() if row["key"] in CAMPAIGNS]
        return [{
            **row,
            "reply_rate": round(row["replied"] / row["sent"] * 100, 1) if row["sent"] else None,
            "prep_label": CAMPAIGNS[row["key"]].prep_label,
            "uses_audit": CAMPAIGNS[row["key"]].uses_audit,
        } for row in known]

    def campaign_results(self, campaign: str) -> list[dict[str, Any]]:
        return [
            {**row, "reply_rate": round(row["replied"] / row["sent"] * 100, 1)}
            for row in self.repository.campaign_results(campaign)
        ]

    def item(self, item_id: str) -> dict[str, Any] | None:
        item = self.repository.item(item_id)
        if item is None:
            return None
        return {
            **item,
            "next_step": next_step(item),
            "gmail_block_reason": gmail_block_reason(item, gmail_connected=self.gmail is not None),
        }

    def sync_gmail(self) -> dict[str, int]:
        """Find drafts that have left Gmail, meaning they were sent or deleted.

        gmail.compose can list drafts but not read the Sent folder, so the two
        can't be told apart. Mike's workflow sends what it drafts, so a draft
        that's gone counts as contacted, and the row says how it was detected.
        """
        if self.gmail is None:
            raise OutreachIntegrationUnavailable("Gmail isn't connected")
        started = datetime.now(timezone.utc)
        try:
            live = self.gmail.list_draft_ids()
        except GmailDraftError as exc:
            raise OutreachIntegrationUnavailable(str(exc)) from exc
        open_items = self.gmail_repository.open_gmail_drafts(started)
        moved = sum(
            1 for item in open_items
            if item["gmail_draft_id"] not in live
            and self.gmail_repository.mark_draft_left_gmail(item["id"], item["gmail_draft_id"])
        )
        return {"checked": len(open_items), "moved_to_contacted": moved}
