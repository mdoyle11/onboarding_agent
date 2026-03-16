"""Composite onboarding tools — combine Graph + DocuSign into human-readable summaries."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.integrations.docusign_client import DocuSignClient
from onboarding_agent.integrations.graph_client import GraphClient

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register all composite onboarding tools on the given FastMCP instance."""

    @mcp.tool()
    async def get_onboarding_status(employee_email: str) -> dict[str, Any]:
        """
        Get a comprehensive onboarding status for an employee by combining data
        from the Excel tracker and DocuSign.

        This is the primary tool for answering HR questions like
        "What's the status of [employee]?" or "Has [employee] signed their offer letter?".

        Parameters:
        - employee_email: The new hire's email address

        Returns a dict with:
        - found (bool) — False if the employee is not in the tracker at all
        - employee_email (str)
        - excel_status (str) — status from the onboarding tracker
        - docusign_envelope_id (str) — empty if no envelope exists
        - docusign_status (str) — e.g. "created", "sent", "completed", empty if none
        - summary (str) — human-readable one-paragraph status suitable for pasting into Teams
        """
        graph_client = GraphClient()
        docusign_client = DocuSignClient()

        tracker = await graph_client.find_employee_in_tracker(employee_email)

        if not tracker.get("found"):
            return {
                "found": False,
                "employee_email": employee_email,
                "excel_status": "",
                "docusign_envelope_id": "",
                "docusign_status": "",
                "summary": (
                    f"No onboarding record found for **{employee_email}** in the tracker. "
                    "They may not have been added yet, or the email address may be incorrect."
                ),
            }

        excel_status = tracker.get("status", "Unknown")
        row_id = tracker.get("row_id", "")

        # Check DocuSign
        ds_check = await docusign_client.check_draft_exists(employee_email)
        envelope_id = ds_check.get("envelope_id", "")
        docusign_status = ""

        if ds_check.get("exists") and envelope_id:
            ds_status = await docusign_client.get_envelope_status(envelope_id)
            docusign_status = ds_status.get("status", "unknown")

        # Build human-readable summary
        ds_line = ""
        if not envelope_id:
            ds_line = "No DocuSign envelope has been created yet."
        elif docusign_status == "created":
            ds_line = "A DocuSign draft has been created but not yet sent."
        elif docusign_status == "sent":
            ds_line = "DocuSign has been sent and is awaiting signature."
        elif docusign_status == "delivered":
            ds_line = "DocuSign was delivered and viewed by the recipient."
        elif docusign_status == "completed":
            ds_line = "DocuSign has been fully signed and completed."
        elif docusign_status == "voided":
            ds_line = "The DocuSign envelope was voided."
        else:
            ds_line = f"DocuSign status: {docusign_status}."

        summary = (
            f"**{employee_email}** — Tracker status: *{excel_status}*. {ds_line}"
        )

        return {
            "found": True,
            "employee_email": employee_email,
            "excel_row_id": row_id,
            "excel_status": excel_status,
            "docusign_envelope_id": envelope_id,
            "docusign_status": docusign_status,
            "summary": summary,
        }
