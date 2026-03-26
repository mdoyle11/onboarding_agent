"""Composite onboarding tools — combine tracker stages + DocuSign into human-readable summaries."""

from __future__ import annotations

import logging
from typing import Any, cast

from fastmcp import FastMCP

from onboarding_agent.integrations.docusign_client import DocuSignClient

logger = logging.getLogger(__name__)

_DS_STATUS_LINES = {
    "":          "No DocuSign envelope has been created yet.",
    "created":   "A DocuSign draft has been created but not yet sent.",
    "sent":      "DocuSign sent — awaiting signature.",
    "delivered": "DocuSign delivered and viewed by recipient.",
    "completed": "DocuSign fully signed and completed.",
    "voided":    "DocuSign envelope was voided.",
}


def _tracker() -> Any:
    from onboarding_agent.integrations.graph_client import GraphClient
    return GraphClient()


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
        record = cast(dict[str, Any], await tracker.get_employee_stages(employee_email))

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
        name = record.get("name", employee_email)

        # DocuSign status
        ds_client = DocuSignClient()
        ds_check = await ds_client.check_draft_exists(employee_email)
        envelope_id = ds_check.get("envelope_id", "")
        docusign_status = ""

        if ds_check.get("exists") and envelope_id:
            ds_result = await ds_client.get_envelope_status(envelope_id)
            docusign_status = ds_result.get("status", "")

        ds_line = _DS_STATUS_LINES.get(docusign_status, f"DocuSign status: {docusign_status}.")

        # Build stage breakdown (active stages only for now)
        active = ["Added to Tracker", "Sent Offer Letter", "Offer Letter Signed"]
        stage_lines = []
        for s in active:
            val = stages.get(s, "")
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
            "stages": stages,
            "docusign_envelope_id": envelope_id,
            "docusign_status": docusign_status,
            "summary": summary,
        }
