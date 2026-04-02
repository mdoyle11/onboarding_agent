"""Staff roster capacity and roster update tools."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from onboarding_agent.mcp_server.clients import staff_roster as _staff_roster
from onboarding_agent.mcp_server.clients import tracker as _tracker


def register(mcp: FastMCP) -> None:
    """Register staff roster tools on the given FastMCP instance."""

    @mcp.tool()
    async def check_staff_roster_capacity(location: str, job_category: str) -> dict[str, Any]:
        return await _staff_roster().check_staff_roster_capacity(location, job_category)

    @mcp.tool()
    async def add_employee_to_staff_roster(
        employee_email: str,
        job_category: str,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        result = await _staff_roster().add_employee_to_staff_roster(
            employee_email,
            job_category,
            location=location,
            job_title=job_title,
            status_change=status_change,
        )
        if result.get("success"):
            await _tracker().update_stage(
                employee_email,
                "Added to Staff Roster",
                location=location,
                job_title=job_title,
                status_change=status_change,
            )

            from onboarding_agent.integrations.card_state import (
                mark_docusign_roster_complete,
                refresh_docusign_status_card,
            )

            card = await mark_docusign_roster_complete(
                employee_email,
                job_category,
                location,
                job_title,
                status_change,
            )
            if card is not None:
                await refresh_docusign_status_card(employee_email, location, job_title, status_change)
        return result
