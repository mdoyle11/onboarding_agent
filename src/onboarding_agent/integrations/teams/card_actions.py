"""Teams adaptive-card action helpers and completion flows."""

from __future__ import annotations

import logging
from typing import Any

from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext

from onboarding_agent.integrations.adaptive_cards import docusign_status_card, new_hire_card
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    get_new_hire_card,
    mark_docusign_roster_complete,
    mark_new_hire_action_complete,
    refresh_new_hire_card,
)
from onboarding_agent.integrations.teams.proactive import send_proactive_message

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
        "work_location": str(value.get("work_location", "")).strip(),
        "job_title": str(value.get("job_title", "")).strip(),
        "status_change": str(value.get("status_change", "")).strip(),
    }


async def card_action_already_completed(card_action: dict[str, str] | None) -> bool:
    if not card_action:
        return False
    card = await get_new_hire_card(
        card_action["employee_email"],
        card_action.get("work_location", ""),
        card_action.get("job_title", ""),
        card_action.get("status_change", ""),
    )
    if not card:
        return False
    if card_action["action"] == "send_onboarding_email":
        return bool(card.get("email_sent"))
    if card_action["action"] == "send_docusign":
        return bool(card.get("docusign_sent"))
    if card_action["action"] == "add_to_staff_roster":
        docusign_card = await get_docusign_status_card(
            card_action["employee_email"],
            card_action.get("work_location", ""),
            card_action.get("job_title", ""),
            card_action.get("status_change", ""),
        )
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
    work_location = card_action.get("work_location", "").strip()
    job_title = card_action.get("job_title", "").strip()
    status_change = card_action.get("status_change", "").strip()

    try:
        from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        tracker_client = TrackerClient()
        if await _staff_roster_stage_completed(
            tracker_client,
            employee_email,
            work_location,
            job_title,
            status_change,
        ):
            await refresh_card_from_context(context, card_action)
            await context.send_activity(already_completed_message(card_action))
            return

        if not job_category:
            await context.send_activity(
                f"Please enter the exact staff roster job category for {employee_email} before submitting."
            )
            return

        result = await StaffRosterClient().add_employee_to_staff_roster(
            employee_email,
            job_category,
            location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
        if result.get("success"):
            await tracker_client.update_stage(
                employee_email,
                "Added to Staff Roster",
                location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
            docusign_card = await mark_docusign_roster_complete(
                employee_email,
                job_category,
                work_location,
                job_title,
                status_change,
            )
            if docusign_card and await _update_docusign_status_card(context, docusign_card):
                return
            await context.send_activity(
                f"Added {employee_email} to the staff roster as {job_category}."
            )
            return

        error = str(result.get("error", "Unknown error"))
        if result.get("multiple_matches"):
            matches = result.get("matches", [])
            if isinstance(matches, list) and matches:
                disambiguation = "; ".join(
                    (
                        f"location={str(match.get('location', '') or 'unknown')}, "
                        f"job_title={str(match.get('job_title', '') or 'unknown')}, "
                        f"added_to_tracker={str(match.get('added_to_tracker', '') or 'unknown')}"
                    )
                    for match in matches
                    if isinstance(match, dict)
                )
                error = f"{error} Matching tracker entries: {disambiguation}"
        await context.send_activity(
            f"Failed to add {employee_email} to the staff roster as {job_category}. {error}"
        )
    except Exception as exc:
        logger.exception("Staff roster card action failed")
        await context.send_activity(
            f"Failed to add {employee_email} to the staff roster as {job_category}. {exc}"
        )


async def _run_new_hire_card_action(card_action: dict[str, str]) -> dict[str, Any]:
    employee_email = card_action["employee_email"]
    work_location = card_action.get("work_location", "").strip()
    job_title = card_action.get("job_title", "").strip()
    status_change = card_action.get("status_change", "").strip()
    action = card_action["action"]

    if action == "send_onboarding_email":
        from onboarding_agent.mcp_server.tools_email import send_onboarding_email_to_employee

        return await send_onboarding_email_to_employee(employee_email)

    if action == "send_docusign":
        from onboarding_agent.integrations.docusign_client import DocuSignClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        docusign_client = DocuSignClient()
        draft_result = await docusign_client.check_draft_exists(
            employee_email,
            work_location,
            job_title,
            status_change,
        )
        if not draft_result.get("exists"):
            card = await get_new_hire_card(employee_email, work_location, job_title, status_change)
            requested_start_date = str((card or {}).get("requested_start_date", "") or "").strip()
            employee_name = str((card or {}).get("employee_name", "") or "").strip()
            if not card or not requested_start_date or not job_title:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "error": (
                        f"No DocuSign draft found for {employee_email} "
                        f"({work_location or 'unknown location'}, {job_title or 'unknown title'}, {status_change or 'unknown status'}), "
                        "and the card state does not include enough data to recreate one."
                    ),
                }
            draft_result = await docusign_client.create_envelope_draft(
                employee_name=employee_name or employee_email,
                employee_email=employee_email,
                start_date=requested_start_date,
                position=job_title,
                work_location=work_location,
                status_change=status_change,
            )
            if not draft_result.get("success"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "error": (
                        f"DocuSign draft was missing for {employee_email} and recreation failed: "
                        f"{draft_result.get('error', 'unknown error')}"
                    ),
                }

        envelope_id = str(draft_result.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": employee_email,
                "error": "DocuSign draft lookup succeeded but returned no envelope_id.",
            }

        send_result = await docusign_client.send_envelope(envelope_id)
        if not send_result.get("success"):
            return send_result

        stage_result = await TrackerClient().update_stage(
            employee_email,
            "Sent Offer Letter",
            location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
        result: dict[str, Any] = dict(send_result)
        if not stage_result.get("success"):
            result["warning"] = f"Offer letter sent, but tracker update failed: {stage_result.get('error', 'unknown error')}"
        return result

    return {"success": False, "employee_email": employee_email, "error": f"Unsupported card action: {action}"}


async def execute_new_hire_card_action_without_context(card_action: dict[str, str]) -> bool:
    result = await _run_new_hire_card_action(card_action)
    if not result.get("success"):
        return False

    await mark_new_hire_action_complete(
        card_action["employee_email"],
        card_action["action"],
        card_action.get("work_location", ""),
        card_action.get("job_title", ""),
        card_action.get("status_change", ""),
    )
    refresh_result = await refresh_new_hire_card(
        card_action["employee_email"],
        card_action.get("work_location", ""),
        card_action.get("job_title", ""),
        card_action.get("status_change", ""),
    )

    warning = str(result.get("warning", "") or "").strip()
    if warning:
        card = await get_new_hire_card(
            card_action["employee_email"],
            card_action.get("work_location", ""),
            card_action.get("job_title", ""),
            card_action.get("status_change", ""),
        )
        if card:
            await send_proactive_message(
                channel_id=card.get("channel_id", ""),
                message=warning,
            )
    return bool(refresh_result.get("success"))


async def notify_card_action_failure(card_action: dict[str, str]) -> None:
    card = await get_new_hire_card(
        card_action["employee_email"],
        card_action.get("work_location", ""),
        card_action.get("job_title", ""),
        card_action.get("status_change", ""),
    )
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
        card = await get_docusign_status_card(
            card_action["employee_email"],
            card_action.get("work_location", ""),
            card_action.get("job_title", ""),
            card_action.get("status_change", ""),
        )
        if not card:
            return False
        return await _update_docusign_status_card(context, card)
    card = await get_new_hire_card(
        card_action["employee_email"],
        card_action.get("work_location", ""),
        card_action.get("job_title", ""),
        card_action.get("status_change", ""),
    )
    if not card:
        return False
    return await _update_new_hire_card(context, card)


async def _staff_roster_stage_completed(
    client: Any,
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> bool:
    try:
        result = await client.get_employee_stages(
            employee_email,
            location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
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


async def _update_card_via_context(
    context: TurnContext, card_state: dict[str, Any], card_dict: dict[str, Any], label: str,
) -> bool:
    """Push an updated adaptive card back to Teams via the turn context."""
    target_id = getattr(context.activity, "reply_to_id", "") or card_state.get("message_id", "")
    if not target_id:
        return False
    activity = Activity(
        type="message",
        id=target_id,
        text="",
        attachments=[
            Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=card_dict,
            )
        ],
    )
    try:
        await context.update_activity(activity)
        logger.info("Updated %s card %s after action", label, target_id)
        return True
    except Exception:
        logger.exception("Failed to update %s card %s", label, target_id)
        return False


async def _update_new_hire_card(context: TurnContext, card: dict[str, Any]) -> bool:
    updated = new_hire_card(
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
    return await _update_card_via_context(context, card, updated, "new-hire")


async def _update_docusign_status_card(context: TurnContext, card: dict[str, Any]) -> bool:
    updated = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
        work_location=card.get("work_location", ""),
        job_title=card.get("job_title", ""),
        status_change=card.get("status_change", ""),
    )
    return await _update_card_via_context(context, card, updated, "DocuSign status")
