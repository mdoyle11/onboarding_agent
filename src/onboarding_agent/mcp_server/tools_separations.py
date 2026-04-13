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
        and Transfer Out workflows. If the user has not specified which
        workflow applies, ask for clarification before calling this tool.
        """
        if not str(status_change or "").strip():
            return {
                "success": False,
                "employee_email": employee_email,
                "location": location,
                "action": "needs_clarification",
                "needs_clarification": True,
                "error": "Please specify whether this move is a Separation or Transfer Out.",
                "summary": (
                    f"Before moving {employee_email} to the Separations sheet, "
                    "please specify whether this is a Separation or Transfer Out."
                ),
            }

        from onboarding_agent.domain.identity import EmployeeIdentity
        from onboarding_agent.integrations.card_state import find_active_separation_cards

        identity = EmployeeIdentity(employee_email, location, job_title, status_change)
        active_cards = await find_active_separation_cards(identity, submission_id=submission_id)
        if not submission_id and len(active_cards) > 1:
            matches = [
                {
                    "submission_id": str(card.get("submission_id", "") or ""),
                    "location": str(card.get("work_location", "") or ""),
                    "job_title": str(card.get("job_title", "") or ""),
                    "status_change": str(card.get("status_change", "") or ""),
                    "employee_name": str(card.get("employee_name", "") or ""),
                }
                for card in active_cards
            ]
            return {
                "success": False,
                "employee_email": employee_email,
                "location": location,
                "action": "needs_clarification",
                "needs_clarification": True,
                "multiple_active_cards": True,
                "matches": matches,
                "error": (
                    "Multiple active separation workflow cards matched this employee. "
                    "Please specify the exact job title, location, or submission."
                ),
                "summary": (
                    f"Before moving {employee_email} to the Separations sheet, "
                    "please specify which active separation/transfer-out workflow applies."
                ),
            }
        matched_card = active_cards[0] if not submission_id and len(active_cards) == 1 else {}
        resolved_submission_id = submission_id or str(matched_card.get("submission_id", "") or "")
        resolved_location = location or str(matched_card.get("work_location", "") or "")
        resolved_job_title = job_title or str(matched_card.get("job_title", "") or "")
        resolved_status_change = status_change or str(matched_card.get("status_change", "") or "")
        identity = EmployeeIdentity(employee_email, resolved_location, resolved_job_title, resolved_status_change)

        roster_client = _staff_roster()
        roster_result = await roster_client.find_employee_in_staff_roster(
            employee_email,
            location=resolved_location,
            job_category=job_category,
            personal_email=employee_email,
            position=resolved_job_title,
        )
        if not roster_result.get("found") and not roster_result.get("multiple_matches"):
            roster_result = await roster_client._resolve_roster_match(
                employee_email,
                location=resolved_location,
                job_category=job_category,
                job_title=resolved_job_title,
                status_change=resolved_status_change,
                submission_id=resolved_submission_id,
            )
        if roster_result.get("multiple_matches"):
            return {
                "success": False,
                "employee_email": employee_email,
                "location": resolved_location,
                "multiple_matches": True,
                "matches": roster_result.get("matches", []),
                "action": "failed",
                "error": (
                    "Multiple staff roster rows matched this employee. "
                    "Please specify the exact group/job category or position."
                ),
                "summary": (
                    f"Failed to record separation for {employee_email}: "
                    "Multiple staff roster rows matched this employee. "
                    "Please specify the exact group/job category or position."
                ),
            }
        if not roster_result.get("found"):
            return {
                "success": False,
                "employee_email": employee_email,
                "location": resolved_location,
                "action": "failed",
                "error": (
                    f"Employee {employee_email} was not found in Staff Roster at {resolved_location}. "
                    "No separation record was created."
                ),
                "summary": (
                    f"Failed to record separation for {employee_email}: "
                    f"Employee was not found in Staff Roster at {resolved_location}. "
                    "No separation record was created."
                ),
            }
        roster_data = roster_result

        sep_result = await _separations().add_separation_record(
            employee_email,
            location=resolved_location,
            employee_name=str((roster_data or {}).get("employee_name", "") or ""),
            status_change=resolved_status_change,
            job_title=resolved_job_title,
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

        # Remove from Staff Roster
        removal_summary = ""
        if roster_data:
            remove_result = await roster_client.remove_employee_from_staff_roster(
                employee_email,
                location=resolved_location,
                job_category=job_category or str(roster_data.get("job_category", "") or ""),
                job_title=resolved_job_title,
                status_change=resolved_status_change,
                submission_id=resolved_submission_id,
            )
            if remove_result.get("success"):
                removal_summary = f" Removed from Staff Roster ({resolved_location})."
            else:
                removal_summary = f" Staff Roster removal failed: {remove_result.get('error', 'unknown')}."

        # Mark tracker stage complete
        await _tracker().update_stage(
            employee_email,
            "Added to Staff Roster",
            location=resolved_location,
            job_title=resolved_job_title,
            status_change=resolved_status_change,
            submission_id=resolved_submission_id,
        )

        # Update card state
        from onboarding_agent.integrations.card_state import (
            mark_separation_action_complete,
            refresh_separation_card,
        )

        card = await mark_separation_action_complete(identity, submission_id=resolved_submission_id)
        if card is not None:
            await refresh_separation_card(identity, submission_id=resolved_submission_id)

        summary_prefix = (
            f"Separation record already existed for {employee_email} at {resolved_location}."
            if sep_result.get("already_exists")
            else f"Separation recorded for {employee_email} at {resolved_location}."
        )
        return {
            **sep_result,
            "summary": f"{summary_prefix}{removal_summary}",
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
        if result.get("multiple_matches"):
            return {
                **result,
                "action": "failed",
                "summary": (
                    f"Leave status update failed for {employee_email}: "
                    "Multiple staff roster rows matched this employee. "
                    "Please specify the exact group/job category or position."
                ),
            }
        return {
            **result,
            "action": "failed",
            "summary": f"Leave status update failed for {employee_email}: {result.get('error', 'unknown error')}",
        }
