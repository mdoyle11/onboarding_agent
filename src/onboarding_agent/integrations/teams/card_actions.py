"""Teams adaptive-card action helpers and completion flows."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage
from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext

from onboarding_agent.integrations.adaptive_cards import docusign_status_card, new_hire_card
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    get_new_hire_card,
    mark_docusign_roster_complete,
    mark_new_hire_action_complete,
    refresh_docusign_status_card,
    refresh_new_hire_card,
)
from onboarding_agent.integrations.teams.proactive import send_proactive_message
from onboarding_agent.integrations.teams.reply import tool_named_succeeded

logger = logging.getLogger(__name__)


def extract_card_action(activity: Any) -> dict[str, str] | None:
    value = getattr(activity, "value", None)
    if not isinstance(value, dict):
        return None

    action = str(value.get("action", "")).strip().lower()
    employee_email = str(value.get("employee_email", "")).strip()
    if not action or not employee_email:
        return None
    return {
        "action": action,
        "employee_email": employee_email,
        "job_category": str(value.get("job_category", "")).strip(),
    }


def card_action_to_command(card_action: dict[str, str] | None) -> str:
    """Translate Adaptive Card Action.Submit payloads into plain-text commands."""
    if not card_action:
        return ""

    action = card_action["action"]
    employee_email = card_action["employee_email"]
    if action == "send_onboarding_email":
        return f"send the onboarding email for {employee_email}"
    if action == "send_docusign":
        return f"send the docusign envelope for {employee_email}"
    if action == "add_to_staff_roster":
        job_category = card_action.get("job_category", "").strip()
        if not job_category:
            return ""
        return f"add {employee_email} to the staff roster using the exact job category {job_category}"
    return ""


async def card_action_already_completed(card_action: dict[str, str] | None) -> bool:
    if not card_action:
        return False
    card = await get_new_hire_card(card_action["employee_email"])
    if not card:
        return False
    if card_action["action"] == "send_onboarding_email":
        return bool(card.get("email_sent"))
    if card_action["action"] == "send_docusign":
        return bool(card.get("docusign_sent"))
    if card_action["action"] == "add_to_staff_roster":
        docusign_card = await get_docusign_status_card(card_action["employee_email"])
        return bool(docusign_card and docusign_card.get("roster_added"))
    return False


def already_completed_message(card_action: dict[str, str]) -> str:
    if card_action["action"] == "send_onboarding_email":
        return f"Welcome email was already sent for {card_action['employee_email']}."
    if card_action["action"] == "add_to_staff_roster":
        return f"Staff roster was already updated for {card_action['employee_email']}."
    return f"Offer letter was already sent for {card_action['employee_email']}."


async def handle_staff_roster_card_action(context: TurnContext, card_action: dict[str, str]) -> None:
    employee_email = card_action["employee_email"]
    job_category = card_action.get("job_category", "").strip()

    try:
        from onboarding_agent.integrations.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.tracker_client import TrackerClient

        tracker_client = TrackerClient()
        if await _staff_roster_stage_completed(tracker_client, employee_email):
            await refresh_card_from_context(context, card_action)
            await context.send_activity(already_completed_message(card_action))
            return

        if not job_category:
            await context.send_activity(
                f"Please enter the exact staff roster job category for {employee_email} before submitting."
            )
            return

        result = await StaffRosterClient().add_employee_to_staff_roster(employee_email, job_category)
        if result.get("success"):
            await tracker_client.update_stage(employee_email, "Added to Staff Roster")
            docusign_card = await mark_docusign_roster_complete(employee_email, job_category)
            if docusign_card and await _update_docusign_status_card(context, docusign_card):
                return
            await context.send_activity(
                f"Added {employee_email} to the staff roster as {job_category}."
            )
            return

        error = str(result.get("error", "Unknown error"))
        await context.send_activity(
            f"Failed to add {employee_email} to the staff roster as {job_category}. {error}"
        )
    except Exception as exc:
        logger.exception("Staff roster card action failed")
        await context.send_activity(
            f"Failed to add {employee_email} to the staff roster as {job_category}. {exc}"
        )


async def complete_card_action(
    context: TurnContext,
    card_action: dict[str, str],
    messages: list[BaseMessage],
) -> bool:
    action = card_action["action"]
    employee_email = card_action["employee_email"]
    if action == "send_onboarding_email":
        tool_name = "send_onboarding_email"
    elif action == "send_docusign":
        tool_name = "send_docusign_envelope"
    else:
        tool_name = "add_employee_to_staff_roster"
    if not tool_named_succeeded(messages, tool_name):
        return False

    if action == "add_to_staff_roster":
        docusign_card = await mark_docusign_roster_complete(
            employee_email,
            card_action.get("job_category", "").strip(),
        )
        if not docusign_card:
            return False
        return await _update_docusign_status_card(context, docusign_card)

    card = await mark_new_hire_action_complete(employee_email, action)
    if not card:
        return False
    return await _update_new_hire_card(context, card)


async def complete_card_action_without_context(
    card_action: dict[str, str],
    messages: list[BaseMessage],
) -> bool:
    action = card_action["action"]
    employee_email = card_action["employee_email"]
    if action == "send_onboarding_email":
        tool_name = "send_onboarding_email"
    elif action == "send_docusign":
        tool_name = "send_docusign_envelope"
    else:
        tool_name = "add_employee_to_staff_roster"

    if not tool_named_succeeded(messages, tool_name):
        return False

    if action == "add_to_staff_roster":
        docusign_card = await mark_docusign_roster_complete(
            employee_email,
            card_action.get("job_category", "").strip(),
        )
        if not docusign_card:
            return False
        result = await refresh_docusign_status_card(employee_email)
        return bool(result.get("success"))

    await mark_new_hire_action_complete(employee_email, action)
    result = await refresh_new_hire_card(employee_email)
    return bool(result.get("success"))


async def notify_card_action_failure(card_action: dict[str, str]) -> None:
    card = await get_new_hire_card(card_action["employee_email"])
    if not card:
        return

    action_labels = {
        "send_onboarding_email": "send the welcome email",
        "send_docusign": "send the offer letter",
        "add_to_staff_roster": "add the employee to the staff roster",
    }
    action_label = action_labels.get(card_action["action"], "complete the requested action")
    await send_proactive_message(
        channel_id=card.get("channel_id", ""),
        message=f"Failed to {action_label} for {card_action['employee_email']}. Check the agent logs for details.",
    )


async def refresh_card_from_context(context: TurnContext, card_action: dict[str, str]) -> bool:
    if card_action["action"] == "add_to_staff_roster":
        card = await get_docusign_status_card(card_action["employee_email"])
        if not card:
            return False
        return await _update_docusign_status_card(context, card)
    card = await get_new_hire_card(card_action["employee_email"])
    if not card:
        return False
    return await _update_new_hire_card(context, card)


async def _staff_roster_stage_completed(client: Any, employee_email: str) -> bool:
    try:
        result = await client.get_employee_stages(employee_email)
    except Exception:
        logger.exception("Failed to verify Added to Staff Roster stage for %s", employee_email)
        return False

    if not result.get("found"):
        return False
    stages = result.get("stages", {})
    if not isinstance(stages, dict):
        return False
    value = stages.get("Added to Staff Roster", "")
    return bool(str(value).strip())


async def _update_new_hire_card(context: TurnContext, card: dict[str, Any]) -> bool:
    target_id = getattr(context.activity, "reply_to_id", "") or card.get("message_id", "")
    if not target_id:
        return False

    updated_card = new_hire_card(
        employee_name=card.get("employee_name", ""),
        employee_email=card.get("employee_email", ""),
        title=card.get("title", ""),
        status_change=card.get("status_change", ""),
        requested_start_date=card.get("requested_start_date", ""),
        job_title=card.get("job_title", ""),
        work_location=card.get("work_location", ""),
        requesting_manager=card.get("requesting_manager", ""),
        summary=card.get("summary", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_sent=bool(card.get("docusign_sent")),
        allow_email_action=bool(card.get("allow_email_action", True)),
        allow_docusign_action=bool(card.get("allow_docusign_action", True)),
    )
    activity = Activity(
        type="message",
        id=target_id,
        text="",
        attachments=[
            Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=updated_card,
            )
        ],
    )
    try:
        await context.update_activity(activity)
        logger.info("Updated new-hire card %s after action", target_id)
        return True
    except Exception:
        logger.exception("Failed to update new-hire card %s", target_id)
        return False


async def _update_docusign_status_card(context: TurnContext, card: dict[str, Any]) -> bool:
    target_id = getattr(context.activity, "reply_to_id", "") or card.get("message_id", "")
    if not target_id:
        return False

    updated_card = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
    )
    activity = Activity(
        type="message",
        id=target_id,
        text="",
        attachments=[
            Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=updated_card,
            )
        ],
    )
    try:
        await context.update_activity(activity)
        logger.info("Updated DocuSign status card %s after roster action", target_id)
        return True
    except Exception:
        logger.exception("Failed to update DocuSign status card %s", target_id)
        return False
