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
        start_date: str,
        department: str,
        location: str,
        manager_email: str,
        summary: str,
    ) -> dict[str, object]:
        from onboarding_agent.integrations.adaptive_cards import new_hire_card
        from onboarding_agent.integrations.card_state import (
            reset_new_hire_card_actions,
            save_new_hire_card,
        )

        await reset_new_hire_card_actions(employee_email)
        card = new_hire_card(
            employee_name,
            employee_email,
            start_date,
            department,
            location,
            manager_email,
            summary,
        )
        result = await _messenger().send_channel_notification(channel_id, summary, card=card)
        if result.get("success") and result.get("message_id"):
            await save_new_hire_card(
                employee_email=employee_email,
                channel_id=channel_id,
                message_id=str(result["message_id"]),
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
    ) -> dict[str, object]:
        from onboarding_agent.integrations.adaptive_cards import docusign_status_card
        from onboarding_agent.integrations.card_state import save_docusign_status_card

        card = docusign_status_card(employee_email, envelope_id, status, summary)
        result = await _messenger().send_channel_notification(channel_id, summary, card=card)
        if result.get("success") and result.get("message_id") and status.lower() == "completed":
            await save_docusign_status_card(
                employee_email=employee_email,
                channel_id=channel_id,
                message_id=str(result["message_id"]),
                envelope_id=envelope_id,
                status=status,
                summary=summary,
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
