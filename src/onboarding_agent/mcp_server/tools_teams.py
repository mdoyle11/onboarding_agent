"""Teams notification tools."""

from __future__ import annotations

from fastmcp import FastMCP

from onboarding_agent.integrations.teams.messenger import TeamsMessenger


def _messenger() -> TeamsMessenger:
    return TeamsMessenger()


def register(mcp: FastMCP) -> None:
    """Register Teams notification tools on the given FastMCP instance."""

    @mcp.tool()
    async def send_teams_channel_notification(channel_id: str, message: str) -> dict[str, object]:
        return await _messenger().send_channel_notification(channel_id, message)

    @mcp.tool()
    async def send_new_hire_card(
        channel_id: str,
        employee_name: str,
        employee_email: str,
        summary: str = "",
        title: str = "",
        status_change: str = "",
        requested_start_date: str = "",
        job_title: str = "",
        work_location: str = "",
        requesting_manager: str = "",
    ) -> dict[str, object]:
        from onboarding_agent.integrations.adaptive_cards import new_hire_card
        from onboarding_agent.integrations.card_state import (
            reset_new_hire_card_actions,
            save_new_hire_card,
        )

        await reset_new_hire_card_actions(employee_email, work_location, job_title, status_change)
        card = new_hire_card(
            employee_name,
            employee_email,
            summary,
            title=title,
            status_change=status_change,
            requested_start_date=requested_start_date,
            job_title=job_title,
            work_location=work_location,
            requesting_manager=requesting_manager,
            allow_email_action=True,
            allow_docusign_action=True,
        )
        result = await _messenger().send_channel_notification(channel_id, summary, card=card)
        if result.get("success") and result.get("message_id"):
            await save_new_hire_card(
                employee_email=employee_email,
                channel_id=channel_id,
                message_id=str(result["message_id"]),
                employee_name=employee_name,
                title=title,
                status_change=status_change,
                requested_start_date=requested_start_date,
                job_title=job_title,
                work_location=work_location,
                requesting_manager=requesting_manager,
                summary=summary,
                allow_email_action=True,
                allow_docusign_action=True,
            )
        return result

    @mcp.tool()
    async def send_docusign_status_card(
        channel_id: str,
        employee_email: str,
        envelope_id: str,
        status: str,
        summary: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, object]:
        from onboarding_agent.integrations.adaptive_cards import docusign_status_card
        from onboarding_agent.integrations.card_state import save_docusign_status_card

        card = docusign_status_card(
            employee_email,
            envelope_id,
            status,
            summary,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
        result = await _messenger().send_channel_notification(channel_id, summary, card=card)
        if result.get("success") and result.get("message_id") and status.lower() == "completed":
            await save_docusign_status_card(
                employee_email=employee_email,
                channel_id=channel_id,
                message_id=str(result["message_id"]),
                envelope_id=envelope_id,
                status=status,
                summary=summary,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
        return result

    @mcp.tool()
    async def send_background_clearance_card(
        channel_id: str,
        employee_name: str,
        employee_email: str,
        summary: str,
    ) -> dict[str, object]:
        from onboarding_agent.integrations.adaptive_cards import background_clearance_card

        card = background_clearance_card(employee_name, employee_email, summary)
        return await _messenger().send_channel_notification(channel_id, summary, card=card)

    @mcp.tool()
    async def send_teams_direct_message(user_id: str, message: str) -> dict[str, object]:
        return await _messenger().send_direct_message(user_id, message)

    @mcp.tool()
    async def send_teams_reply(activity_id: str, message: str) -> dict[str, object]:
        return await _messenger().send_reply(activity_id, message)
