"""Excel tracker and Teams notification tools."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Stage definitions for the Excel tracker
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
    """Return the Microsoft Graph Excel tracker client."""
    from onboarding_agent.integrations.graph_client import GraphClient
    return GraphClient()


def register(mcp: FastMCP) -> None:
    """Register all tracker and notification tools on the given FastMCP instance."""

    @mcp.tool()
    async def find_employee_in_tracker(employee_email: str) -> dict[str, Any]:
        """
        Search the Excel onboarding tracker for an employee by email.

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
        location: str = "",
    ) -> dict[str, Any]:
        """
        Append a new employee row to the Excel onboarding tracker and
        automatically mark the "Added to Tracker" stage with today's date.

        Parameters:
        - name: Full name of the new hire
        - email: Corporate email address
        - start_date: ISO 8601 date string (YYYY-MM-DD)
        - department: Department name
        - manager_email: Hiring manager's email
        - location: Office location / campus (e.g. "Miami", "Remote")

        Returns a dict with:
        - success (bool)
        - row_id (str) — identifier of the newly created row
        """
        return await _tracker().add_employee_to_tracker(name, email, start_date, department, manager_email, location)

    @mcp.tool()
    async def update_tracker_stage(employee_email: str, stage_name: str) -> dict[str, Any]:
        """
        Mark a pipeline stage as completed for an employee in the Excel tracker.
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
        """
        Return the full pipeline stage breakdown for an employee from the Excel tracker.

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
    async def list_employees(pending_stage: str = "") -> dict[str, Any]:
        """
        List all employees in the Excel onboarding tracker.

        Parameters:
        - pending_stage: Optional. If provided, only returns employees who have
          NOT yet completed this stage (i.e. the stage date is blank/empty).
          Leave blank to return all employees regardless of stage.

        Valid stage names:
          "Added to Tracker", "Sent Offer Letter", "Offer Letter Signed",
          "Background Submission", "Background Cleared", "Added to ADP",
          "Complete in ADP", "Clear to Start", "Prorations Sent"

        Use this to answer questions like:
          "Who is pending / waiting for signature?" → pending_stage="Offer Letter Signed"
          "Who hasn't been added yet?" → pending_stage="Added to Tracker"
          "List everyone in onboarding" → no filter
          "How many people are in the pipeline?" → no filter

        Returns a dict with:
        - count (int) — number of matching employees
        - pending_stage (str) — the filter applied, or "" if none
        - employees (list) — each has: name, email, start_date, department, stages (dict)
        - summary (str) — human-readable answer ready to send to the user
        """
        result = await _tracker().list_all_employees()
        if not result.get("success"):
            return result

        employees = result["employees"]
        if pending_stage:
            employees = [e for e in employees if not e["stages"].get(pending_stage)]

        # Build human-readable summary
        if not employees:
            if pending_stage:
                summary = f"No employees are pending **{pending_stage}** — all have completed it."
            else:
                summary = "The tracker is empty — no employees have been added yet."
        else:
            if pending_stage:
                summary = (
                    f"**{len(employees)} employee(s)** are pending **{pending_stage}**:\n"
                    + "\n".join(f"  • {e['name']} ({e['email']})" for e in employees)
                )
            else:
                summary = (
                    f"**{len(employees)} employee(s)** in the tracker:\n"
                    + "\n".join(f"  • {e['name']} ({e['email']})" for e in employees)
                )

        return {"count": len(employees), "pending_stage": pending_stage, "employees": employees, "summary": summary}

    @mcp.tool()
    async def get_form_submission_by_id(submission_id: str) -> dict[str, Any]:
        """
        Fetch a specific Microsoft Forms submission by its ID.
        """
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().get_form_submission_by_id(submission_id)

    @mcp.tool()
    async def send_teams_channel_notification(channel_id: str, message: str) -> dict[str, Any]:
        """Post a message to a Microsoft Teams channel."""
        from onboarding_agent.integrations.graph_client import GraphClient
        return await GraphClient().send_teams_channel_notification(channel_id, message)

    @mcp.tool()
    async def send_new_hire_card(
        channel_id: str,
        employee_name: str,
        employee_email: str,
        start_date: str,
        department: str,
        location: str,
        manager_email: str,
        summary: str,
    ) -> dict[str, Any]:
        """Post a rich new hire Adaptive Card to a Teams channel."""
        from onboarding_agent.integrations.adaptive_cards import new_hire_card
        from onboarding_agent.integrations.card_state import save_new_hire_card
        from onboarding_agent.integrations.graph_client import GraphClient

        card = new_hire_card(
            employee_name,
            employee_email,
            start_date,
            department,
            location,
            manager_email,
            summary,
        )
        result = await GraphClient().send_teams_channel_notification(channel_id, summary, card=card)
        if result.get("success") and result.get("message_id"):
            save_new_hire_card(
                employee_email=employee_email,
                channel_id=channel_id,
                message_id=result["message_id"],
                employee_name=employee_name,
                start_date=start_date,
                department=department,
                location=location,
                manager_email=manager_email,
                summary=summary,
            )
        return result

    @mcp.tool()
    async def send_docusign_status_card(
        channel_id: str,
        employee_email: str,
        envelope_id: str,
        status: str,
        summary: str,
    ) -> dict[str, Any]:
        """Post a DocuSign status Adaptive Card to a Teams channel."""
        from onboarding_agent.integrations.adaptive_cards import docusign_status_card
        from onboarding_agent.integrations.graph_client import GraphClient

        card = docusign_status_card(employee_email, envelope_id, status, summary)
        return await GraphClient().send_teams_channel_notification(channel_id, summary, card=card)

    @mcp.tool()
    async def send_background_clearance_card(
        channel_id: str,
        employee_name: str,
        employee_email: str,
        summary: str,
    ) -> dict[str, Any]:
        """Post a background clearance Adaptive Card to a Teams channel."""
        from onboarding_agent.integrations.adaptive_cards import background_clearance_card
        from onboarding_agent.integrations.graph_client import GraphClient

        card = background_clearance_card(employee_name, employee_email, summary)
        return await GraphClient().send_teams_channel_notification(channel_id, summary, card=card)

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
