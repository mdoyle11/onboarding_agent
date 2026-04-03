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
        """Check whether a matching DocuSign draft exists for one workflow row.

        Use this before sending an offer letter. If duplicate tracker rows share
        the same email, pass `work_location`, `job_title`, and/or
        `status_change` when available. When only one matching tracker row still
        needs an offer letter, this tool can resolve it automatically; otherwise
        it returns an ambiguity error instead of guessing.
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
        """Create a DocuSign offer-letter draft, but do not send it yet.

        This uses the configured template and returns an envelope in `created`
        status. Call `send_docusign_envelope` afterward to actually send it.
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
        """Send an existing DocuSign draft envelope by envelope ID.

        Use this after `check_docusign_draft_exists` or
        `create_docusign_envelope_draft`. This tool sends the envelope but does
        not update tracker stages on its own.
        """
        client = _docusign()
        result = await client.send_envelope(envelope_id)
        return result

    @mcp.tool()
    async def get_docusign_envelope_status(envelope_id: str) -> dict[str, Any]:
        """Retrieve the current DocuSign status and recipient tracking for an envelope."""
        client = _docusign()
        return await client.get_envelope_status(envelope_id)
