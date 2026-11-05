"""Bulk outreach actions: change many queue items at once, and take a prospect
from 'not contacted' to 'Gmail draft ready' in one call.

Every step re-uses the single-item service, so the same guards apply
(suppression list, verification, no duplicate Gmail drafts). Nothing here
sends email: the end of the line is a Gmail draft Mike reviews in Gmail.
"""
from __future__ import annotations

from typing import Any

from app.campaigns import DEFAULT_CAMPAIGN, get_campaign
from app.services.audit_reports import AuditReportError, AuditReportService
from app.services.outreach import (
    OutreachBlocked,
    OutreachConflict,
    OutreachIntegrationUnavailable,
    OutreachService,
    uses_old_copy,
)

MAX_BULK = 50
_FAILURES = (OutreachBlocked, OutreachConflict, OutreachIntegrationUnavailable, AuditReportError)


def bulk_set_status(outreach: OutreachService, item_ids: list[str], status: str) -> list[dict[str, Any]]:
    results = []
    for item_id in list(dict.fromkeys(item_ids))[:MAX_BULK]:
        current = outreach.repository.get_item(item_id)
        if current is None:
            results.append({"id": item_id, "ok": False, "detail": "not found"})
            continue
        if current["status"] == status:
            results.append({"id": item_id, "ok": True, "detail": "already set"})
            continue
        try:
            outreach.update_item(item_id, changes={"status": status},
                                 expected_version=current["version"])
            results.append({"id": item_id, "ok": True})
        except _FAILURES as exc:
            results.append({"id": item_id, "ok": False, "detail": str(exc)})
    return results


def fast_track(
    outreach: OutreachService,
    audits: AuditReportService,
    place_id: str,
    *,
    gmail: bool = True,
    campaign_key: str = DEFAULT_CAMPAIGN,
    angle: str | None = None,
) -> dict[str, Any]:
    """Audit PDF -> queue email -> generate draft -> Draft ready -> Gmail draft.

    Campaigns that don't use an audit skip that step.

    Stops at the first step that fails and says which one and why; steps
    already done stay done, so running it again picks up where it stopped.
    """
    steps: list[str] = []

    def stop(step: str, detail: str, item: dict | None = None) -> dict[str, Any]:
        return {"place_id": place_id, "ok": False, "failed_step": step, "detail": detail,
                "steps": steps, "item_id": (item or {}).get("id")}

    # Picking up a lead that stopped partway keeps its draft (and any edits).
    campaign = get_campaign(campaign_key)
    waiting = outreach.cooldown_block(place_id, campaign_key)
    if waiting:
        return stop("cooldown", waiting)
    existing = outreach.repository.find_email_item(place_id, campaign_key)
    # A draft in the old copy is rewritten unless it's already in Gmail.
    resuming = bool(existing and existing.get("body") and existing.get("claim_signal") == campaign.claim_signal
                    and (existing.get("gmail_draft_id") or not uses_old_copy(existing)))

    # 1. Fresh audit report (the email is written from it and attaches it).
    if not resuming and campaign.uses_audit:
        created = audits.create_default_reports([place_id])
        result = created[0] if created else {"status": "skipped", "detail": "no result"}
        if result.get("status") != "created":
            return stop("audit", result.get("detail") or "no reportable findings for an audit")
        steps.append("audit")

    # 2. Queue (idempotent: returns the existing queue item if there is one).
    try:
        item = outreach.create_item(place_id, "email", None, campaign_key)
    except _FAILURES as exc:
        return stop("queue", str(exc))
    if item is None:
        return stop("queue", "prospect not found")
    steps.append("queue")
    item = outreach.repository.get_item(item["id"]) or item

    if item.get("gmail_draft_id"):
        steps.append("gmail_draft")
        return {"place_id": place_id, "ok": True, "steps": steps, "item_id": item["id"],
                "detail": "Gmail draft already existed"}

    # 3. Generate the draft from the new audit.
    if not resuming:
        try:
            item = outreach.generate_draft(item["id"], expected_version=item["version"], angle=angle) or item
        except _FAILURES as exc:
            return stop("draft", str(exc), item)
        if item.get("status") == "no_outreach_finding" or not item.get("body"):
            return stop("draft", "no finding strong enough to write an email about", item)
        steps.append("draft")

    # 4. Mark it ready.
    if item.get("status") not in {"draft_ready", "approved"}:
        try:
            item = outreach.update_item(item["id"], changes={"status": "draft_ready"},
                                        expected_version=item["version"]) or item
        except _FAILURES as exc:
            return stop("ready", str(exc), item)
    steps.append("ready")

    # 5. Put it in Gmail as a draft (never sent).
    if gmail:
        try:
            outreach.create_gmail_draft(item["id"], expected_version=item["version"])
        except _FAILURES as exc:
            return stop("gmail_draft", str(exc), item)
        steps.append("gmail_draft")

    return {"place_id": place_id, "ok": True, "steps": steps, "item_id": item["id"]}
