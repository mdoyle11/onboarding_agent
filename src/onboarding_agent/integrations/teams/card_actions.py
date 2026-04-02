"""Teams adaptive-card action helpers and completion flows."""

from __future__ import annotations

import logging
from typing import Any

from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext

from onboarding_agent.domain.identity import EmployeeIdentity
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


def _identity_from_action(card_action: dict[str, str]) -> EmployeeIdentity:
    return EmployeeIdentity.from_dict(card_action)


async def card_action_already_completed(card_action: dict[str, str] | None) -> bool:
    if not card_action:
        return False
    identity = _identity_from_action(card_action)
    card = await get_new_hire_card(identity)
    if not card:
        return False
    if card_action["action"] == "send_onboarding_email":
        return bool(card.get("email_sent"))
    if card_action["action"] == "send_docusign":
        return bool(card.get("docusign_sent"))
    if card_action["action"] == "add_to_staff_roster":
        from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        employee = await TrackerClient().find_employee_in_tracker(
            identity.email,
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
        )
        membership = await StaffRosterClient().find_employee_in_staff_roster(
            identity.email,
            location=identity.work_location,
            personal_email=identity.email,
            employee_name=str(employee.get("name", "") or ""),
            position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
        )
        return bool(membership.get("found"))
    return False


def already_completed_message(card_action: dict[str, str]) -> str:
    if card_action["action"] == "send_onboarding_email":
        return f"Welcome email was already sent for {card_action['employee_email']}."
    if card_action["action"] == "add_to_staff_roster":
        return f"Staff roster was already updated for {card_action['employee_email']}."
    return f"Offer letter was already sent for {card_action['employee_email']}."


async def handle_staff_roster_card_action(context: TurnContext, card_action: dict[str, str]) -> None:
    identity = _identity_from_action(card_action)
    job_category = card_action.get("job_category", "").strip()

    try:
        from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        staff_roster_client = StaffRosterClient()
        tracker_client = TrackerClient()
        employee = await tracker_client.find_employee_in_tracker(
            identity.email,
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
        )
        existing_roster_entry = await staff_roster_client.find_employee_in_staff_roster(
            identity.email,
            location=identity.work_location,
            personal_email=identity.email,
            employee_name=str(employee.get("name", "") or ""),
            position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
        )
        if existing_roster_entry.get("found"):
            existing_job_category = str(existing_roster_entry.get("job_category", "") or job_category)
            await tracker_client.update_stage(
                identity.email,
                "Added to Staff Roster",
                location=identity.work_location,
                job_title=identity.job_title,
                status_change=identity.status_change,
            )
            docusign_card = await mark_docusign_roster_complete(identity, existing_job_category)
            if docusign_card:
                await _update_docusign_status_card(context, docusign_card)
            await refresh_card_from_context(context, card_action)
            await context.send_activity(
                f"Staff roster already contains {identity.email} in {identity.work_location or 'the selected location'} as {existing_job_category or 'the saved group'}."
            )
            return

        if not job_category:
            await context.send_activity(
                f"Please enter the exact staff roster job category for {identity.email} before submitting."
            )
            return

        result = await staff_roster_client.add_employee_to_staff_roster(
            identity.email,
            job_category,
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
        )
        if result.get("success"):
            await tracker_client.update_stage(
                identity.email,
                "Added to Staff Roster",
                location=identity.work_location,
                job_title=identity.job_title,
                status_change=identity.status_change,
            )
            docusign_card = await mark_docusign_roster_complete(identity, job_category)
            if docusign_card:
                await _update_docusign_status_card(context, docusign_card)
            detail = "already existed" if result.get("already_exists") else "was added"
            await context.send_activity(
                f"Staff roster update succeeded: {identity.email} {detail} in {identity.work_location or 'the selected location'} as {job_category}."
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
            f"Staff roster update failed for {identity.email} as {job_category}. {error}"
        )
    except Exception as exc:
        logger.exception("Staff roster card action failed")
        await context.send_activity(
            f"Staff roster update failed for {identity.email} as {job_category}. {exc}"
        )


async def _run_new_hire_card_action(card_action: dict[str, str]) -> dict[str, Any]:
    identity = _identity_from_action(card_action)
    action = card_action["action"]

    if action == "send_onboarding_email":
        from onboarding_agent.mcp_server.tools_email import send_onboarding_email_to_employee

        return await send_onboarding_email_to_employee(identity.email)

    if action == "send_docusign":
        from onboarding_agent.integrations.docusign_client import DocuSignClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        docusign_client = DocuSignClient()
        draft_result = await docusign_client.check_draft_exists(
            identity.email,
            identity.work_location,
            identity.job_title,
            identity.status_change,
        )
        if not draft_result.get("exists"):
            card = await get_new_hire_card(identity)
            requested_start_date = str((card or {}).get("requested_start_date", "") or "").strip()
            employee_name = str((card or {}).get("employee_name", "") or "").strip()
            if not card or not requested_start_date or not identity.job_title:
                return {
                    "success": False,
                    "employee_email": identity.email,
                    "error": (
                        f"No DocuSign draft found for {identity.email} "
                        f"({identity.work_location or 'unknown location'}, {identity.job_title or 'unknown title'}, {identity.status_change or 'unknown status'}), "
                        "and the card state does not include enough data to recreate one."
                    ),
                }
            draft_result = await docusign_client.create_envelope_draft(
                employee_name=employee_name or identity.email,
                employee_email=identity.email,
                start_date=requested_start_date,
                position=identity.job_title,
                work_location=identity.work_location,
                status_change=identity.status_change,
            )
            if not draft_result.get("success"):
                return {
                    "success": False,
                    "employee_email": identity.email,
                    "error": (
                        f"DocuSign draft was missing for {identity.email} and recreation failed: "
                        f"{draft_result.get('error', 'unknown error')}"
                    ),
                }

        envelope_id = str(draft_result.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": identity.email,
                "error": "DocuSign draft lookup succeeded but returned no envelope_id.",
            }

        send_result = await docusign_client.send_envelope(envelope_id)
        if not send_result.get("success"):
            return send_result

        stage_result = await TrackerClient().update_stage(
            identity.email,
            "Sent Offer Letter",
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
        )
        result: dict[str, Any] = dict(send_result)
        if not stage_result.get("success"):
            result["warning"] = f"Offer letter sent, but tracker update failed: {stage_result.get('error', 'unknown error')}"
        return result

    return {"success": False, "employee_email": identity.email, "error": f"Unsupported card action: {action}"}


async def execute_new_hire_card_action_without_context(card_action: dict[str, str]) -> bool:
    identity = _identity_from_action(card_action)
    result = await _run_new_hire_card_action(card_action)
    if not result.get("success"):
        return False

    await mark_new_hire_action_complete(identity, card_action["action"])
    refresh_result = await refresh_new_hire_card(identity)

    warning = str(result.get("warning", "") or "").strip()
    if warning:
        card = await get_new_hire_card(identity)
        if card:
            await send_proactive_message(
                channel_id=card.get("channel_id", ""),
                message=warning,
            )
    return bool(refresh_result.get("success"))


async def notify_card_action_failure(card_action: dict[str, str]) -> None:
    identity = _identity_from_action(card_action)
    card = await get_new_hire_card(identity)
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
        message=f"Failed to {action_label} for {identity.email}. Check the agent logs for details.",
    )


async def refresh_card_from_context(context: TurnContext, card_action: dict[str, str]) -> bool:
    identity = _identity_from_action(card_action)
    if card_action["action"] == "add_to_staff_roster":
        card = await get_docusign_status_card(identity)
        if not card:
            return False
        return await _update_docusign_status_card(context, card)
    card = await get_new_hire_card(identity)
    if not card:
        return False
    return await _update_new_hire_card(context, card)


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
