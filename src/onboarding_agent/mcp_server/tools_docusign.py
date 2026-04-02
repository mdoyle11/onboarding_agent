"""DocuSign tools — envelope draft creation, sending, and status checks."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.mcp_server.clients import docusign as _docusign
from onboarding_agent.mcp_server.clients import tracker as _tracker

logger = logging.getLogger(__name__)


async def _resolve_unsent_offer_letter_match(employee_email: str) -> dict[str, Any]:
    tracker_result = await _tracker().find_employee_in_tracker(employee_email)
    matches = tracker_result.get("matches", [])
    if not tracker_result.get("multiple_matches") or not isinstance(matches, list) or not matches:
        return {}

    unsent_matches: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        location = str(match.get("location", "") or "")
        job_title = str(match.get("job_title", "") or "")
        status_change = str(match.get("status_change", "") or "")
        stages_result = await _tracker().get_employee_stages(
            employee_email,
            location=location,
            job_title=job_title,
            status_change=status_change,
        )
        stages = stages_result.get("stages", {})
        if not isinstance(stages, dict):
            continue
        sent_offer_letter = str(stages.get("Sent Offer Letter", "") or "").strip()
        if not sent_offer_letter:
            unsent_matches.append({
                "location": location,
                "job_title": job_title,
                "status_change": status_change,
            })

    if len(unsent_matches) == 1:
        return {"resolved": True, **unsent_matches[0], "matches": matches}
    return {"resolved": False, "matches": matches}


def register(mcp: FastMCP) -> None:
    """Register all DocuSign tools on the given FastMCP instance."""

    @mcp.tool()
    async def check_docusign_draft_exists(
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        """
        Check whether a DocuSign envelope draft already exists for an employee.

        Parameters:
        - employee_email: The new hire's email address

        Returns a dict with:
        - exists (bool)
        - envelope_id (str) — empty string if no draft exists
        """
        if not (work_location or job_title or status_change):
            resolved = await _resolve_unsent_offer_letter_match(employee_email)
            if resolved.get("resolved"):
                work_location = str(resolved.get("location", "") or "")
                job_title = str(resolved.get("job_title", "") or "")
                status_change = str(resolved.get("status_change", "") or "")
            elif resolved.get("matches"):
                return {
                    "exists": False,
                    "envelope_id": "",
                    "multiple_matches": True,
                    "matches": resolved.get("matches", []),
                    "error": (
                        "Multiple tracker rows match this email and more than one still needs an offer letter. "
                        "Provide work_location, job_title, or status_change before checking DocuSign."
                    ),
                }
        client = _docusign()
        result = await client.check_draft_exists(employee_email, work_location, job_title, status_change)
        if work_location:
            result["work_location"] = work_location
        if job_title:
            result["job_title"] = job_title
        if status_change:
            result["status_change"] = status_change
        return result

    @mcp.tool()
    async def create_docusign_envelope_draft(
        employee_name: str,
        employee_email: str,
        start_date: str,
        position: str,
        work_location: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        """
        Create a DocuSign envelope draft using the configured template.

        Uses templateRoles to pre-fill signer details. The envelope is created
        in "created" (draft) status — it is NOT sent until send_docusign_envelope is called.

        Parameters:
        - employee_name: Full name of the new hire (used as templateRole name)
        - employee_email: New hire's email (used as templateRole email / signer)
        - start_date: ISO 8601 date string (YYYY-MM-DD)
        - position: Employee position / job title

        Returns a dict with:
        - success (bool)
        - envelope_id (str)
        - status (str) — should be "created"
        """
        client = _docusign()
        return await client.create_envelope_draft(
            employee_name,
            employee_email,
            start_date,
            position,
            work_location,
            status_change,
        )

    @mcp.tool()
    async def send_docusign_envelope(envelope_id: str) -> dict[str, Any]:
        """
        Push a DocuSign envelope from draft ("created") to sent status.

        This triggers DocuSign to email the signing request to all recipients
        defined in the envelope template.

        Parameters:
        - envelope_id: The DocuSign envelope ID to send

        Returns a dict with:
        - success (bool)
        - envelope_id (str)
        - status (str) — should be "sent"
        """
        client = _docusign()
        result = await client.send_envelope(envelope_id)
        return result

    @mcp.tool()
    async def get_docusign_envelope_status(envelope_id: str) -> dict[str, Any]:
        """
        Retrieve the current status and recipient tracking for a DocuSign envelope.

        Parameters:
        - envelope_id: The DocuSign envelope ID

        Returns a dict with:
        - envelope_id (str)
        - status (str) — one of: created, sent, delivered, completed, voided
        - recipients (list[dict]) — each with name, email, status, signed_date_time
        """
        client = _docusign()
        return await client.get_envelope_status(envelope_id)
