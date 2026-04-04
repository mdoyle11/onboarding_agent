"""Staff roster capacity and roster CRUD tools."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from onboarding_agent.mcp_server.clients import staff_roster as _staff_roster
from onboarding_agent.mcp_server.clients import tracker as _tracker


def register(mcp: FastMCP) -> None:
    """Register staff roster tools on the given FastMCP instance."""

    @mcp.tool()
    async def check_staff_roster_capacity(location: str, job_category: str) -> dict[str, Any]:
        """Check roster capacity for one location workbook and exact Group value.

        Use this for questions like "What's the capacity for Teacher at Collier?".
        `location` selects the workbook. `job_category` should be the intended
        roster `Group` value; simple singular/plural variants are normalized to
        the closest matching group when the meaning is clear.
        """
        return await _staff_roster().check_staff_roster_capacity(location, job_category)

    @mcp.tool()
    async def find_employee_in_staff_roster(
        employee_email: str,
        location: str,
        job_category: str = "",
        personal_email: str = "",
        employee_name: str = "",
        position: str = "",
    ) -> dict[str, Any]:
        """Inspect an employee's current staff-roster row in one location workbook.

        Prefer this before editing or deleting roster rows, or when HR asks what
        values are currently in the roster. Matching prefers `personal_email`,
        then work email, then name plus position fallback for older rows.
        """
        return await _staff_roster().find_employee_in_staff_roster(
            employee_email,
            location=location,
            job_category=job_category,
            personal_email=personal_email,
            employee_name=employee_name,
            position=position,
        )

    @mcp.tool()
    async def add_employee_to_staff_roster(
        employee_email: str,
        job_category: str,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Add an employee to the section-aware staff roster for a Group.

        This uses the location-specific roster workbook, inserts above that
        group's `Totals` row, verifies the workbook write, and then marks
        tracker stage `Added to Staff Roster` complete on success.

        Use `job_category` as the exact roster `Group` value.
        """
        result = await _staff_roster().add_employee_to_staff_roster(
            employee_email,
            job_category,
            location=location,
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
                mark_docusign_roster_complete,
                refresh_docusign_status_card,
            )

            identity = EmployeeIdentity(employee_email, location, job_title, status_change)
            card = await mark_docusign_roster_complete(identity, job_category)
            if card is not None:
                await refresh_docusign_status_card(identity)
            detail = "already existed" if result.get("already_exists") else "was added"
            return {
                **result,
                "action": "already_exists" if result.get("already_exists") else "added",
                "summary": (
                    f"Staff roster update succeeded: {employee_email} {detail} "
                    f"in {location or result.get('location', '') or 'the selected location'} as {job_category}."
                ),
            }
        return {
            **result,
            "action": "failed",
            "summary": (
                f"Staff roster update failed for {employee_email} as {job_category}. "
                f"{result.get('error', 'Unknown error')}"
            ),
        }

    @mcp.tool()
    async def remove_employee_from_staff_roster(
        employee_email: str,
        location: str = "",
        job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Remove an employee from the location-specific staff roster workbook.

        This deletes the matched worksheet row, verifies removal, and clears the
        tracker stage `Added to Staff Roster` on success. Provide the fullest
        available identity when duplicate tracker rows may exist.
        """
        result = await _staff_roster().remove_employee_from_staff_roster(
            employee_email,
            location=location,
            job_category=job_category,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )
        if result.get("success"):
            await _tracker().update_stage(
                employee_email,
                "Added to Staff Roster",
                value="",
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            return {
                **result,
                "action": "removed",
                "summary": (
                    f"Staff roster update succeeded: {employee_email} was removed "
                    f"from {location or result.get('location', '') or 'the selected location'}"
                    f"{f' group {job_category}' if job_category else ''}."
                ),
            }
        return {
            **result,
            "action": "failed",
            "summary": (
                f"Staff roster removal failed for {employee_email}. "
                f"{result.get('error', 'Unknown error')}"
            ),
        }

    @mcp.tool()
    async def update_employee_in_staff_roster(
        employee_email: str,
        location: str = "",
        current_job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
        employee_id: str = "",
        job_category: str = "",
        position: str = "",
        work_email: str = "",
        personal_email: str = "",
        employee_name: str = "",
        grade_level: str = "",
        subject: str = "",
        supplements: str = "",
        talent: str = "",
        background_eligibility: str = "",
        date_approved: str = "",
        license_value: str = "",
        nine_cell: str = "",
        notes: str = "",
        roster_status: str = "",
        nti_culture: str = "",
        nti_content: str = "",
        mupd_culture: str = "",
        mupd_content: str = "",
        rt_boy_pd_content: str = "",
        cc_1: str = "",
        cc_2: str = "",
        cc_3: str = "",
    ) -> dict[str, Any]:
        """Edit an existing staff-roster row, including section-aware Group moves.

        This tool supports broad row updates such as `employee_id`,
        `employee_name`, `position`, `work_email`, `personal_email`,
        `roster_status`, `grade_level`, `subject`, `supplements`, `talent`,
        `background_eligibility`, `date_approved`, `license_value`,
        `nine_cell`, `notes`, `nti_culture`, `nti_content`, `mupd_culture`,
        `mupd_content`, `rt_boy_pd_content`, `cc_1`, `cc_2`, and `cc_3`.

        If `job_category` changes, the employee is moved into the target
        group's section above its `Totals` row. Use `current_job_category`
        when needed to disambiguate the existing roster row.
        """
        result = await _staff_roster().update_employee_in_staff_roster(
            employee_email,
            location=location,
            current_job_category=current_job_category,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
            employee_id=employee_id,
            job_category=job_category,
            position=position,
            work_email=work_email,
            personal_email=personal_email,
            employee_name=employee_name,
            grade_level=grade_level,
            subject=subject,
            supplements=supplements,
            talent=talent,
            background_eligibility=background_eligibility,
            date_approved=date_approved,
            license_value=license_value,
            nine_cell=nine_cell,
            notes=notes,
            roster_status=roster_status,
            nti_culture=nti_culture,
            nti_content=nti_content,
            mupd_culture=mupd_culture,
            mupd_content=mupd_content,
            rt_boy_pd_content=rt_boy_pd_content,
            cc_1=cc_1,
            cc_2=cc_2,
            cc_3=cc_3,
        )
        if result.get("success"):
            return {
                **result,
                "action": "updated",
                "summary": (
                    f"Staff roster update succeeded for {employee_email}"
                    f"{f' in {location}' if location else ''}"
                    f"{f' as {job_category}' if job_category else ''}."
                ),
            }
        return {
            **result,
            "action": "failed",
            "summary": (
                f"Staff roster edit failed for {employee_email}. "
                f"{result.get('error', 'Unknown error')}"
            ),
        }
