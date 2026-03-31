"""Composite onboarding tools — combine tracker stages + DocuSign into human-readable summaries."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.config import settings
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    save_docusign_status_card,
)
from onboarding_agent.integrations.docusign_client import DocuSignClient
from onboarding_agent.integrations.teams.messenger import TeamsMessenger
from onboarding_agent.integrations.tracker_client import TrackerClient

logger = logging.getLogger(__name__)

_DS_STATUS_LINES = {
    "":          "No DocuSign envelope has been created yet.",
    "created":   "A DocuSign draft has been created but not yet sent.",
    "sent":      "DocuSign sent — awaiting signature.",
    "delivered": "DocuSign delivered and viewed by recipient.",
    "completed": "DocuSign fully signed and completed.",
    "voided":    "DocuSign envelope was voided.",
}


def _tracker() -> TrackerClient:
    return TrackerClient()


async def _reconcile_completed_docusign(
    *,
    tracker: TrackerClient,
    employee_email: str,
    employee_name: str,
    envelope_id: str,
    stages: dict[str, str],
) -> dict[str, str]:
    if stages.get("Offer Letter Signed"):
        return stages

    result = await tracker.update_stage(employee_email, "Offer Letter Signed")
    if not result.get("success"):
        logger.warning(
            "Failed to reconcile Offer Letter Signed for %s: %s",
            employee_email,
            result.get("error", "unknown error"),
        )
        return stages

    updated_stages = dict(stages)
    updated_stages["Offer Letter Signed"] = str(result.get("value", "") or "")

    channel_id = settings.notification_channel().strip()
    if not channel_id:
        return updated_stages

    existing_card = await get_docusign_status_card(employee_email)
    if existing_card and str(existing_card.get("status", "")).lower() == "completed":
        return updated_stages

    summary = (
        f"DocuSign envelope {envelope_id[:8]}{'...' if len(envelope_id) > 8 else ''} "
        f"for {employee_name or employee_email} ({employee_email}) is completed. "
        "The tracker has been updated to Offer Letter Signed."
    )
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card

    card = docusign_status_card(employee_email, envelope_id, "completed", summary)
    teams_result = await TeamsMessenger().send_channel_notification(channel_id, summary, card=card)
    if teams_result.get("success") and teams_result.get("message_id"):
        await save_docusign_status_card(
            employee_email=employee_email,
            channel_id=channel_id,
            message_id=str(teams_result["message_id"]),
            envelope_id=envelope_id,
            status="completed",
            summary=summary,
        )
    else:
        logger.warning(
            "Failed to send reconciled DocuSign completion card for %s: %s",
            employee_email,
            teams_result.get("error", "unknown error"),
        )

    return updated_stages


def _format_stage_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed.strftime("%m/%d/%Y")
        except ValueError:
            continue

    try:
        excel_serial = float(raw)
        excel_epoch = date(1899, 12, 30)
        parsed = excel_epoch.fromordinal(excel_epoch.toordinal() + int(excel_serial))
        return parsed.strftime("%m/%d/%Y")
    except ValueError:
        return raw


def register(mcp: FastMCP) -> None:
    """Register all composite onboarding tools on the given FastMCP instance."""

    @mcp.tool()
    async def get_onboarding_status(employee_email: str) -> dict[str, Any]:
        """
        Get a comprehensive onboarding status for an employee, combining pipeline
        stage tracking and DocuSign envelope status.

        This is the primary tool for HR queries like:
          "What's the status of [employee]?"
          "Has [employee] signed their offer letter?"
          "Where is [employee] in the pipeline?"

        Parameters:
        - employee_email: The new hire's email address

        Returns a dict with:
        - found (bool)
        - employee_email (str)
        - name (str)
        - stages (dict) — all pipeline stages with completion dates or "" if pending
        - docusign_envelope_id (str)
        - docusign_status (str) — created | sent | delivered | completed | voided
        - summary (str) — full human-readable status with per-stage breakdown
        """
        tracker = _tracker()
        record = await tracker.get_employee_stages(employee_email)

        if not record.get("found"):
            return {
                "found": False,
                "employee_email": employee_email,
                "stages": {},
                "docusign_envelope_id": "",
                "docusign_status": "",
                "summary": (
                    f"No onboarding record found for **{employee_email}**. "
                    "They may not have been added yet, or the email may be incorrect."
                ),
            }

        stages: dict[str, str] = record.get("stages", {})
        formatted_stages = {stage: _format_stage_date(value) for stage, value in stages.items()}
        name = record.get("name", employee_email)

        # DocuSign status
        ds_client = DocuSignClient()
        envelope_id = ""
        docusign_status = ""

        ds_draft = await ds_client.check_draft_exists(employee_email)
        if ds_draft.get("exists"):
            envelope_id = str(ds_draft.get("envelope_id", "") or "")
            if envelope_id:
                ds_result = await ds_client.get_envelope_status(envelope_id)
                docusign_status = str(ds_result.get("status", "") or "")

        if not envelope_id:
            ds_latest = await ds_client.find_latest_envelope_for_employee(employee_email)
            if ds_latest.get("found"):
                envelope_id = str(ds_latest.get("envelope_id", "") or "")
                docusign_status = str(ds_latest.get("status", "") or docusign_status)
                if envelope_id:
                    ds_result = await ds_client.get_envelope_status(envelope_id)
                    docusign_status = str(ds_result.get("status", "") or docusign_status)

        if not envelope_id:
            stored_card = await get_docusign_status_card(employee_email)
            if stored_card:
                envelope_id = str(stored_card.get("envelope_id", "") or "")
                docusign_status = str(stored_card.get("status", "") or "")

        if docusign_status.lower() == "completed":
            stages = await _reconcile_completed_docusign(
                tracker=tracker,
                employee_email=employee_email,
                employee_name=name,
                envelope_id=envelope_id,
                stages=stages,
            )
            formatted_stages = {stage: _format_stage_date(value) for stage, value in stages.items()}

        if not docusign_status:
            if stages.get("Offer Letter Signed"):
                docusign_status = "completed"
            elif stages.get("Sent Offer Letter"):
                docusign_status = "sent"

        ds_line = _DS_STATUS_LINES.get(docusign_status, f"DocuSign status: {docusign_status}.")

        # Build stage breakdown (active stages only for now)
        active = ["Added to Tracker", "Added to Staff Roster", "Sent Offer Letter", "Offer Letter Signed"]
        stage_lines = []
        for s in active:
            val = formatted_stages.get(s, "")
            icon = "✓" if val else "○"
            stage_lines.append(f"  {icon} {s}: {val or 'pending'}")

        summary = (
            f"**{name}** ({employee_email})\n"
            + "\n".join(stage_lines)
            + f"\n\nDocuSign: {ds_line}"
        )

        return {
            "found": True,
            "employee_email": employee_email,
            "name": name,
            "stages": formatted_stages,
            "docusign_envelope_id": envelope_id,
            "docusign_status": docusign_status,
            "summary": summary,
        }
