"""Separation and leave-status tools."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from onboarding_agent.mcp_server.clients import separations as _separations
from onboarding_agent.mcp_server.clients import staff_roster as _staff_roster
from onboarding_agent.mcp_server.clients import tracker as _tracker


def register(mcp: FastMCP) -> None:
    """Register separation and leave tools on the given FastMCP instance."""

    @mcp.tool()
    async def record_separation(
        employee_email: str,
        location: str,
        job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
        effective_date: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Record a separation or transfer-out on the Separations sheet.

        This finds the employee in the Staff Roster, copies their data to the
        Separations sheet, removes them from the Staff Roster, and marks the
        tracker stage ``Added to Staff Roster`` complete. Use for Separation
        and Transfer Out workflows.
        """
        roster_client = _staff_roster()
        roster_result = await roster_client.find_employee_in_staff_roster(
            employee_email,
            location=location,
            job_category=job_category,
        )
        roster_data = roster_result if roster_result.get("found") else None

        sep_result = await _separations().add_separation_record(
            employee_email,
            location=location,
            employee_name=str((roster_data or {}).get("employee_name", "") or ""),
            status_change=status_change,
            job_title=job_title,
            job_category=job_category or str((roster_data or {}).get("job_category", "") or ""),
            effective_date=effective_date,
            notes=notes,
            roster_data=roster_data,
        )

        if not sep_result.get("success"):
            return {
                **sep_result,
                "action": "failed",
                "summary": f"Failed to record separation for {employee_email}: {sep_result.get('error', 'unknown error')}",
            }

        if sep_result.get("already_exists"):
            return {
                **sep_result,
                "summary": f"Separation record already exists for {employee_email} at {location}.",
            }

        # Remove from Staff Roster
        removal_summary = ""
        if roster_data:
            remove_result = await roster_client.remove_employee_from_staff_roster(
                employee_email,
                location=location,
                job_category=job_category or str(roster_data.get("job_category", "") or ""),
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            if remove_result.get("success"):
                removal_summary = f" Removed from Staff Roster ({location})."
            else:
                removal_summary = f" Staff Roster removal failed: {remove_result.get('error', 'unknown')}."

        # Mark tracker stage complete
        await _tracker().update_stage(
            employee_email,
            "Added to Staff Roster",
            location=location,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )

        # Update card state
        from onboarding_agent.domain.identity import EmployeeIdentity
        from onboarding_agent.integrations.card_state import (
            mark_separation_action_complete,
            refresh_separation_card,
        )

        identity = EmployeeIdentity(employee_email, location, job_title, status_change)
        card = await mark_separation_action_complete(identity, submission_id=submission_id)
        if card is not None:
            await refresh_separation_card(identity, submission_id=submission_id)

        return {
            **sep_result,
            "summary": f"Separation recorded for {employee_email} at {location}.{removal_summary}",
        }

    @mcp.tool()
    async def find_separation_record(
        employee_email: str,
        location: str,
        status_change: str = "",
    ) -> dict[str, Any]:
        """Look up an existing separation record for an employee."""
        return await _separations().find_separation_record(
            employee_email,
            location=location,
            status_change=status_change,
        )

    @mcp.tool()
    async def update_leave_status(
        employee_email: str,
        location: str,
        status: str,
        note: str = "",
        job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Update the leave status on an employee's Staff Roster row.

        Set ``status`` to ``On Leave`` for Leave Start or ``Active`` for Leave
        End. Optionally appends a ``note`` with the date.  Marks the tracker
        stage ``Added to Staff Roster`` complete on success.
        """
        result = await _staff_roster().update_employee_leave_status(
            employee_email,
            location=location,
            status=status,
            note=note,
            job_category=job_category,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )

        if result.get("success"):
            await _tracker().update_stage(
                employee_email,
                "Added to Staff Roster",
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )

            from onboarding_agent.domain.identity import EmployeeIdentity
            from onboarding_agent.integrations.card_state import (
                mark_separation_action_complete,
                refresh_separation_card,
            )

            identity = EmployeeIdentity(employee_email, location, job_title, status_change)
            card = await mark_separation_action_complete(identity, submission_id=submission_id)
            if card is not None:
                await refresh_separation_card(identity, submission_id=submission_id)

            return {
                **result,
                "action": "updated",
                "summary": f"Leave status updated for {employee_email} at {location}: {status}.",
            }
        return {
            **result,
            "action": "failed",
            "summary": f"Leave status update failed for {employee_email}: {result.get('error', 'unknown error')}",
        }
