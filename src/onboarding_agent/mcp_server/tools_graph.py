"""Tracker + notification tools — dispatches to Google Sheets or Excel based on config."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)


def _tracker():
    """Return the active tracker client based on TRACKER_BACKEND."""
    if settings.is_sheets():
        from onboarding_agent.integrations.sheets_client import SheetsClient
        return SheetsClient()
    from onboarding_agent.integrations.graph_client import GraphClient
    return GraphClient()


def register(mcp: FastMCP) -> None:
    """Register all tracker and notification tools on the given FastMCP instance."""

    _backend = "Google Sheets" if settings.is_sheets() else "Excel"

    @mcp.tool()
    async def find_employee_in_tracker(employee_email: str) -> dict[str, Any]:
        f"""
        Search the {_backend} onboarding tracker for an employee by email.

        Returns a dict with keys:
        - found (bool)
        - row_id (str) — row identifier, empty if not found
        - status (str) — current onboarding status, empty if not found
        """
        return await _tracker().find_employee_in_tracker(employee_email)

    @mcp.tool()
    async def add_employee_to_tracker(
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
    ) -> dict[str, Any]:
        """
        Append a new employee row to the Excel onboarding tracker.

        Parameters:
        - name: Full name of the new hire
        - email: Corporate email address
        - start_date: ISO 8601 date string (YYYY-MM-DD)
        - department: Department name
        - manager_email: Hiring manager's email

        Returns a dict with:
        - success (bool)
        - row_id (str) — identifier of the newly created row
        """
        return await _tracker().add_employee_to_tracker(name, email, start_date, department, manager_email)

    @mcp.tool()
    async def update_tracker_status(row_id: str, new_status: str) -> dict[str, Any]:
        f"""
        Update the status cell for an existing employee row in the {_backend} tracker.

        Parameters:
        - row_id: Row identifier returned by find_employee_in_tracker or add_employee_to_tracker
        - new_status: New status string (e.g. "DocuSign Sent", "Completed")

        Returns a dict with:
        - success (bool)
        - row_id (str)
        - new_status (str)
        """
        return await _tracker().update_tracker_status(row_id, new_status)

    @mcp.tool()
    async def get_form_submission_by_id(submission_id: str) -> dict[str, Any]:
        """
        Fetch a specific Microsoft Forms submission by its ID.

        Returns the raw form answers as a dict, or an error dict if not found.
        Only available when TRACKER_BACKEND=excel (Microsoft Graph).
        """
        if settings.is_sheets():
            return {"found": False, "error": "Forms lookup not available with Google Sheets backend"}
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().get_form_submission_by_id(submission_id)

    @mcp.tool()
    async def send_teams_channel_notification(channel_id: str, message: str) -> dict[str, Any]:
        """
        Post a message to a Microsoft Teams channel.

        Parameters:
        - channel_id: The Teams channel ID (e.g. "19:xxx@thread.tacv2")
        - message: The message text to post (plain text or basic markdown)

        Returns a dict with:
        - success (bool)
        - message_id (str)
        """
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_channel_notification(channel_id, message)

    @mcp.tool()
    async def send_teams_direct_message(user_id: str, message: str) -> dict[str, Any]:
        """
        Send a 1:1 Teams direct message to a user.

        Parameters:
        - user_id: Azure AD object ID of the recipient
        - message: Message text

        Returns a dict with:
        - success (bool)
        - chat_id (str)
        """
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_direct_message(user_id, message)

    @mcp.tool()
    async def send_teams_reply(activity_id: str, message: str) -> dict[str, Any]:
        """
        Reply to an existing Teams thread (e.g. the HR query thread).

        Parameters:
        - activity_id: The ID of the Teams activity/message to reply to
        - message: Reply text

        Returns a dict with success (bool).
        """
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_reply(activity_id, message)
