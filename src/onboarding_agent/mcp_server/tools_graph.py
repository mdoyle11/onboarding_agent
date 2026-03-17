"""Tracker + notification tools — dispatches to Google Sheets or Excel based on config."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

# Stage definitions (kept in sync with sheets_client.STAGES)
_ALL_STAGES = [
    "Added to Tracker",
    "Sent Offer Letter",
    "Offer Letter Signed",
    "Background Submission",
    "Background Cleared",
    "Added to ADP",
    "Complete in ADP",
    "Clear to Start",
    "Prorations Sent",
]
_ACTIVE_STAGES = ["Added to Tracker", "Sent Offer Letter", "Offer Letter Signed"]


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

        Returns a dict with:
        - found (bool)
        - row_id (str) — row identifier, empty if not found
        - stages (dict) — all stage columns keyed by stage name, values are completion
          dates (YYYY-MM-DD) or empty string if not yet completed
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
        f"""
        Append a new employee row to the {_backend} onboarding tracker and
        automatically mark the "Added to Tracker" stage with today's date.

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
    async def update_tracker_stage(employee_email: str, stage_name: str) -> dict[str, Any]:
        f"""
        Mark a pipeline stage as completed for an employee in the {_backend} tracker.
        Records today's date in the corresponding stage column.

        Currently active stages (phases 1-3):
          - "Added to Tracker"
          - "Sent Offer Letter"
          - "Offer Letter Signed"

        Future stages (not yet active):
          - "Background Submission", "Background Cleared", "Added to ADP",
            "Complete in ADP", "Clear to Start", "Prorations Sent"

        Parameters:
        - employee_email: The employee's email address
        - stage_name: Exact stage name from the list above

        Returns a dict with:
        - success (bool)
        - stage (str)
        - value (str) — the date recorded
        """
        return await _tracker().update_stage(employee_email, stage_name)

    @mcp.tool()
    async def get_employee_stages(employee_email: str) -> dict[str, Any]:
        f"""
        Return the full pipeline stage breakdown for an employee from the {_backend} tracker.

        Use this to answer questions like:
          "What stage is [employee] at?"
          "Has [employee] signed their offer letter?"
          "Which employees are pending background checks?"

        Returns a dict with:
        - found (bool)
        - employee_email (str)
        - name (str)
        - start_date (str)
        - stages (dict) — each stage name mapped to its completion date or "" if not done
        - summary (str) — human-readable pipeline status
        """
        if settings.is_sheets():
            from onboarding_agent.integrations.sheets_client import SheetsClient
            result = await SheetsClient().get_employee_stages(employee_email)
        else:
            from onboarding_agent.integrations.graph_client import GraphClient
            result = await GraphClient().find_employee_in_tracker(employee_email)

        if not result.get("found"):
            return {
                "found": False,
                "employee_email": employee_email,
                "stages": {},
                "summary": f"No record found for {employee_email} in the tracker.",
            }

        stages: dict[str, str] = result.get("stages", {})
        name = result.get("name", employee_email)

        # Build human-readable summary
        completed = [s for s in _ALL_STAGES if stages.get(s)]
        pending = [s for s in _ALL_STAGES if not stages.get(s)]
        last_completed = completed[-1] if completed else None
        next_pending = pending[0] if pending else None

        if not completed:
            summary = f"**{name}** has been added to the system but no stages are complete yet."
        elif not next_pending:
            summary = f"**{name}** has completed all pipeline stages."
        else:
            summary = (
                f"**{name}** — last completed stage: *{last_completed}* "
                f"({stages[last_completed]}). Next: *{next_pending}*."
            )

        # Append detail for active stages
        lines = [f"  • {s}: {stages.get(s) or 'pending'}" for s in _ACTIVE_STAGES]
        summary += "\n" + "\n".join(lines)

        return {**result, "summary": summary}

    @mcp.tool()
    async def get_form_submission_by_id(submission_id: str) -> dict[str, Any]:
        """
        Fetch a specific Microsoft Forms submission by its ID.
        Only available when TRACKER_BACKEND=excel.
        """
        if settings.is_sheets():
            return {"found": False, "error": "Forms lookup not available with Google Sheets backend"}
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().get_form_submission_by_id(submission_id)

    @mcp.tool()
    async def send_teams_channel_notification(channel_id: str, message: str) -> dict[str, Any]:
        """Post a message to a Microsoft Teams channel."""
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_channel_notification(channel_id, message)

    @mcp.tool()
    async def send_teams_direct_message(user_id: str, message: str) -> dict[str, Any]:
        """Send a 1:1 Teams direct message to a user."""
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_direct_message(user_id, message)

    @mcp.tool()
    async def send_teams_reply(activity_id: str, message: str) -> dict[str, Any]:
        """Reply to an existing Teams thread."""
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_reply(activity_id, message)
