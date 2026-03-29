"""DocuSign tools — envelope draft creation, sending, and status checks."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.integrations.docusign_client import DocuSignClient

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register all DocuSign tools on the given FastMCP instance."""

    @mcp.tool()
    async def check_docusign_draft_exists(employee_email: str) -> dict[str, Any]:
        """
        Check whether a DocuSign envelope draft already exists for an employee.

        Parameters:
        - employee_email: The new hire's email address

        Returns a dict with:
        - exists (bool)
        - envelope_id (str) — empty string if no draft exists
        """
        client = DocuSignClient()
        return await client.check_draft_exists(employee_email)

    @mcp.tool()
    async def create_docusign_envelope_draft(
        employee_name: str,
        employee_email: str,
        start_date: str,
        department: str,
    ) -> dict[str, Any]:
        """
        Create a DocuSign envelope draft using the configured template.

        Uses templateRoles to pre-fill signer details. The envelope is created
        in "created" (draft) status — it is NOT sent until send_docusign_envelope is called.

        Parameters:
        - employee_name: Full name of the new hire (used as templateRole name)
        - employee_email: New hire's email (used as templateRole email / signer)
        - start_date: ISO 8601 date string (YYYY-MM-DD)
        - department: Department name

        Returns a dict with:
        - success (bool)
        - envelope_id (str)
        - status (str) — should be "created"
        """
        client = DocuSignClient()
        return await client.create_envelope_draft(employee_name, employee_email, start_date, department)

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
        client = DocuSignClient()
        result = await client.send_envelope(envelope_id)
        if result.get("success"):
            from onboarding_agent.integrations.card_state import (
                mark_new_hire_action_complete,
                refresh_new_hire_card,
            )

            status = await client.get_envelope_status(envelope_id)
            recipients = status.get("recipients", [])
            employee_email = ""
            if recipients:
                employee_email = recipients[0].get("email", "") or ""

            if employee_email:
                card = await mark_new_hire_action_complete(employee_email, "send_docusign")
                if card is not None:
                    await refresh_new_hire_card(employee_email)
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
        client = DocuSignClient()
        return await client.get_envelope_status(envelope_id)
