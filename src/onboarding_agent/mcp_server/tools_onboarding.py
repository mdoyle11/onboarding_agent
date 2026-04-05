"""Composite onboarding tools — combine tracker stages + DocuSign into human-readable summaries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

from onboarding_agent.config import settings
from onboarding_agent.domain.formatting import format_date
from onboarding_agent.domain.identity import EmployeeIdentity
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    save_docusign_status_card,
)
from onboarding_agent.integrations.workbook.schema import ALL_STAGES
from onboarding_agent.mcp_server.clients import docusign as _docusign
from onboarding_agent.mcp_server.clients import messenger as _messenger
from onboarding_agent.mcp_server.clients import tracker as _tracker

logger = logging.getLogger(__name__)

_DS_STATUS_LINES = {
    "":          "No DocuSign envelope has been created yet.",
    "created":   "A DocuSign draft has been created but not yet sent.",
    "sent":      "DocuSign sent — awaiting signature.",
    "delivered": "DocuSign delivered and viewed by recipient.",
    "completed": "DocuSign fully signed and completed.",
    "voided":    "DocuSign envelope was voided.",
}


async def _reconcile_completed_docusign(
    *,
    tracker: TrackerClient,
    employee_email: str,
    employee_name: str,
    envelope_id: str,
    stages: dict[str, str],
    location: str = "",
    job_title: str = "",
    status_change: str = "",
    submission_id: str = "",
) -> dict[str, str]:
    if stages.get("Offer Letter Signed"):
        return stages

    result = await tracker.update_stage(
        employee_email,
        "Offer Letter Signed",
        location=location,
        job_title=job_title,
        status_change=status_change,
        submission_id=submission_id,
    )
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

    existing_card = await get_docusign_status_card(
        EmployeeIdentity(employee_email, location, job_title, status_change),
        submission_id=submission_id,
    )
    if existing_card and str(existing_card.get("status", "")).lower() == "completed":
        return updated_stages

    summary = (
        f"DocuSign envelope {envelope_id[:8]}{'...' if len(envelope_id) > 8 else ''} "
        f"for {employee_name or employee_email} ({employee_email}) is completed. "
        "The tracker has been updated to Offer Letter Signed."
    )
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card

    card = docusign_status_card(
        employee_email,
        envelope_id,
        "completed",
        summary,
        employee_name=employee_name or employee_email,
        work_location=location,
        job_title=job_title,
        status_change=status_change,
    )
    teams_result = await _messenger().send_channel_notification(channel_id, summary, card=card)
    if teams_result.get("success") and teams_result.get("message_id"):
        await save_docusign_status_card(
            employee_email=employee_email,
            employee_name=employee_name or employee_email,
            channel_id=channel_id,
            message_id=str(teams_result["message_id"]),
            envelope_id=envelope_id,
            status="completed",
            summary=summary,
            submission_id=submission_id,
            work_location=location,
            job_title=job_title,
            status_change=status_change,
        )
    else:
        logger.warning(
            "Failed to send reconciled DocuSign completion card for %s: %s",
            employee_email,
            teams_result.get("error", "unknown error"),
        )

    return updated_stages


def register(mcp: FastMCP) -> None:
    """Register all composite onboarding tools on the given FastMCP instance."""

    @mcp.tool()
    async def get_onboarding_status(
        employee_email: str,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Get the primary HR-facing onboarding status summary for one employee.

        This combines tracker stages with DocuSign state and should be the
        first tool for questions like "What's their status?", "Was the offer
        letter sent?", or "Has the employee signed?".

        When duplicate tracker rows exist for the same email, pass
        `location`, `job_title`, or `status_change` to disambiguate.
        """
        tracker = _tracker()
        record = await tracker.get_employee_stages(
            employee_email,
            location=location,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )

        if not record.get("found"):
            matches = record.get("matches", [])
            if record.get("multiple_matches") and isinstance(matches, list) and matches:
                lines = []
                for match in matches:
                    if not isinstance(match, dict):
                        continue
                    lines.append(
                        "  • "
                        f"location={match.get('location', '') or 'unknown'}, "
                        f"job_title={match.get('job_title', '') or 'unknown'}, "
                        f"added_to_tracker={match.get('added_to_tracker', '') or 'unknown'}"
                    )
                return {
                    "found": False,
                    "employee_email": employee_email,
                    "submission_id": submission_id,
                    "stages": {},
                    "docusign_envelope_id": "",
                    "docusign_status": "",
                    "multiple_matches": True,
                    "matches": matches,
                    "summary": (
                        f"Multiple onboarding records matched **{employee_email}**. "
                        "Provide location and/or job title to disambiguate.\n"
                        + "\n".join(lines)
                    ),
                }
            return {
                "found": False,
                "employee_email": employee_email,
                "submission_id": submission_id,
                "stages": {},
                "docusign_envelope_id": "",
                "docusign_status": "",
                "summary": (
                    f"No onboarding record found for **{employee_email}**. "
                    "They may not have been added yet, or the email may be incorrect."
                ),
            }

        stages: dict[str, str] = record.get("stages", {})
        formatted_stages = {stage: format_date(value) for stage, value in stages.items()}
        name = record.get("name", employee_email)

        # DocuSign status
        ds_client = _docusign()
        envelope_id = ""
        docusign_status = ""

        ds_draft = await ds_client.check_draft_exists(employee_email, location, job_title, status_change)
        if ds_draft.get("exists"):
            envelope_id = str(ds_draft.get("envelope_id", "") or "")
            if envelope_id:
                ds_result = await ds_client.get_envelope_status(envelope_id)
                docusign_status = str(ds_result.get("status", "") or "")

        if not envelope_id:
            ds_latest = await ds_client.find_latest_envelope_for_employee(
                employee_email,
                location,
                job_title,
                status_change,
            )
            if ds_latest.get("found"):
                envelope_id = str(ds_latest.get("envelope_id", "") or "")
                docusign_status = str(ds_latest.get("status", "") or docusign_status)
                if envelope_id:
                    ds_result = await ds_client.get_envelope_status(envelope_id)
                    docusign_status = str(ds_result.get("status", "") or docusign_status)

        if not envelope_id:
            stored_card = await get_docusign_status_card(
                EmployeeIdentity(employee_email, location, job_title, status_change),
                submission_id=submission_id,
            )
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
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            formatted_stages = {stage: format_date(value) for stage, value in stages.items()}

        if not docusign_status:
            if stages.get("Offer Letter Signed"):
                docusign_status = "completed"
            elif stages.get("Sent Offer Letter"):
                docusign_status = "sent"

        ds_line = _DS_STATUS_LINES.get(docusign_status, f"DocuSign status: {docusign_status}.")

        stage_lines = []
        for s in ALL_STAGES:
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
            "submission_id": record.get("submission_id", submission_id),
            "name": name,
            "stages": formatted_stages,
            "docusign_envelope_id": envelope_id,
            "docusign_status": docusign_status,
            "summary": summary,
        }
