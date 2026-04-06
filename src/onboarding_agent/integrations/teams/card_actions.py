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
    refresh_docusign_status_card,
    refresh_new_hire_card,
    save_docusign_status_card,
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
    card_action = {
        "action": action,
        "employee_email": employee_email,
        "submission_id": str(value.get("submission_id", "")).strip(),
        "job_category": str(value.get("job_category", "")).strip(),
        "work_location": str(value.get("work_location", "")).strip(),
        "job_title": str(value.get("job_title", "")).strip(),
        "status_change": str(value.get("status_change", "")).strip(),
        "message_id": str(getattr(activity, "reply_to_id", "") or getattr(activity, "id", "") or "").strip(),
    }
    logger.info(
        "Extracted card action: action=%s employee=%s submission_id=%s message_id=%s location=%s job_title=%s status_change=%s",
        card_action["action"],
        card_action["employee_email"],
        card_action["submission_id"] or "<missing>",
        card_action["message_id"] or "<missing>",
        card_action["work_location"] or "<missing>",
        card_action["job_title"] or "<missing>",
        card_action["status_change"] or "<missing>",
    )
    return card_action


def _identity_from_action(card_action: dict[str, str]) -> EmployeeIdentity:
    return EmployeeIdentity.from_dict(card_action)


async def _submission_id_for_identity(identity: EmployeeIdentity) -> str:
    try:
        card_state = await get_new_hire_card(identity)
    except AssertionError:
        return ""
    return str((card_state or {}).get("submission_id", "") or "").strip()


async def _resolve_tracker_record_for_docusign_action(card_action: dict[str, str]) -> dict[str, Any]:
    from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

    identity = _identity_from_action(card_action)
    submission_id = str(card_action.get("submission_id", "") or "").strip()
    if not submission_id:
        submission_id = await _submission_id_for_identity(identity)
    return await TrackerClient().resolve_employee_relaxed(
        identity.email,
        location=identity.work_location,
        job_title=identity.job_title,
        status_change=identity.status_change,
        submission_id=submission_id,
    )


async def card_action_already_completed(card_action: dict[str, str] | None) -> bool:
    if not card_action:
        return False
    identity = _identity_from_action(card_action)
    submission_id = str(card_action.get("submission_id", "") or "").strip()
    card = await get_new_hire_card(identity, submission_id=submission_id)
    if card_action["action"] == "send_onboarding_email":
        if not card:
            return False
        return bool(card.get("email_sent"))
    if card_action["action"] == "create_docusign_draft":
        docusign_card = await get_docusign_status_card(identity, submission_id=submission_id)
        if docusign_card and str(docusign_card.get("status", "")).lower() in {"created", "sent", "completed", "delivered"}:
            return True
        return bool(card and card.get("docusign_draft_created"))
    if card_action["action"] == "send_docusign":
        ds_card = await get_docusign_status_card(identity, submission_id=submission_id)
        return bool(ds_card and str(ds_card.get("status", "")).lower() in {"sent", "completed", "delivered"})
    if card_action["action"] == "add_to_staff_roster":
        if not card:
            return False
        from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        employee = await TrackerClient().find_employee_in_tracker(
            identity.email,
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
            submission_id=submission_id or await _submission_id_for_identity(identity),
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
    if card_action["action"] == "create_docusign_draft":
        return f"Offer letter draft was already created for {card_action['employee_email']}."
    if card_action["action"] == "refresh_review_link":
        return f"Review link was already refreshed for {card_action['employee_email']}."
    return f"Offer letter was already sent for {card_action['employee_email']}."


async def handle_staff_roster_card_action(context: TurnContext, card_action: dict[str, str]) -> None:
    identity = _identity_from_action(card_action)
    job_category = card_action.get("job_category", "").strip()

    try:
        from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        staff_roster_client = StaffRosterClient()
        tracker_client = TrackerClient()
        submission_id = str(card_action.get("submission_id", "") or "").strip() or await _submission_id_for_identity(identity)
        employee = await tracker_client.find_employee_in_tracker(
            identity.email,
            location=identity.work_location,
            job_title=identity.job_title,
            status_change=identity.status_change,
            submission_id=submission_id,
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
                submission_id=submission_id,
            )
            docusign_card = await mark_docusign_roster_complete(identity, existing_job_category, submission_id=submission_id)
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
            submission_id=submission_id,
        )
        if result.get("success"):
            await tracker_client.update_stage(
                identity.email,
                "Added to Staff Roster",
                location=identity.work_location,
                job_title=identity.job_title,
                status_change=identity.status_change,
                submission_id=submission_id,
            )
            docusign_card = await mark_docusign_roster_complete(identity, job_category, submission_id=submission_id)
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
    action_submission_id = str(card_action.get("submission_id", "") or "").strip()

    if action == "send_onboarding_email":
        from onboarding_agent.mcp_server.tools_email import send_onboarding_email_to_employee

        return await send_onboarding_email_to_employee(identity.email)

    if action == "create_docusign_draft":
        from onboarding_agent.integrations.docusign_client import DocuSignClient
        from onboarding_agent.integrations.teams.messenger import TeamsMessenger

        logger.info(
            "Starting draft card action: employee=%s submission_id=%s location=%s job_title=%s status_change=%s message_id=%s",
            identity.email,
            action_submission_id or "<missing>",
            identity.work_location or "<missing>",
            identity.job_title or "<missing>",
            identity.status_change or "<missing>",
            card_action.get("message_id", "") or "<missing>",
        )
        parent_card = await get_new_hire_card(identity, submission_id=action_submission_id)
        if not parent_card:
            logger.warning(
                "Draft card action missing parent card: employee=%s submission_id=%s location=%s job_title=%s status_change=%s",
                identity.email,
                action_submission_id or "<missing>",
                identity.work_location or "<missing>",
                identity.job_title or "<missing>",
                identity.status_change or "<missing>",
            )
            return {
                "success": False,
                "employee_email": identity.email,
                "error": f"No stored submission card state for {identity.email}.",
            }
        if action_submission_id and not str(parent_card.get("submission_id", "") or "").strip():
            parent_card["submission_id"] = action_submission_id

        tracker_record = await _resolve_tracker_record_for_docusign_action(card_action)
        logger.info(
            "Draft card action tracker resolution: employee=%s submission_id=%s found=%s multiple_matches=%s tracker_submission_id=%s",
            identity.email,
            action_submission_id or "<missing>",
            bool(tracker_record.get("found")),
            bool(tracker_record.get("multiple_matches", False)),
            str(tracker_record.get("submission_id", "") or "").strip() or "<missing>",
        )
        if not tracker_record.get("found"):
            return {
                "success": False,
                "employee_email": identity.email,
                "error": str(
                    tracker_record.get("error", f"Tracker row not found for {identity.email}.")
                ),
                "multiple_matches": bool(tracker_record.get("multiple_matches", False)),
                "matches": tracker_record.get("matches", []),
            }

        current_work_location = str(tracker_record.get("location", "") or identity.work_location or "").strip()
        current_job_title = str(tracker_record.get("job_title", "") or identity.job_title or "").strip()
        current_status_change = str(tracker_record.get("status_change", "") or identity.status_change or "").strip()
        docusign_client = DocuSignClient()
        draft_result = await docusign_client.check_draft_exists(
            identity.email,
            current_work_location,
            current_job_title,
            current_status_change,
        )
        logger.info(
            "Draft card action check_draft_exists: employee=%s submission_id=%s exists=%s envelope_id=%s",
            identity.email,
            str(tracker_record.get("submission_id", "") or action_submission_id or "").strip() or "<missing>",
            bool(draft_result.get("exists")),
            str(draft_result.get("envelope_id", "") or "").strip() or "<missing>",
        )
        if not draft_result.get("exists"):
            requested_start_date = str(tracker_record.get("start_date", "") or "").strip()
            employee_name = str(tracker_record.get("name", "") or parent_card.get("employee_name", "") or "").strip()
            if not requested_start_date or not current_job_title or not current_work_location:
                logger.warning(
                    "Draft card action missing required tracker fields: employee=%s submission_id=%s start_date=%s location=%s job_title=%s",
                    identity.email,
                    str(tracker_record.get("submission_id", "") or action_submission_id or "").strip() or "<missing>",
                    requested_start_date or "<missing>",
                    current_work_location or "<missing>",
                    current_job_title or "<missing>",
                )
                return {
                    "success": False,
                    "employee_email": identity.email,
                    "error": "Tracker does not contain enough data to create the offer letter draft.",
                }
            draft_result = await docusign_client.create_envelope_draft(
                employee_name=employee_name or identity.email,
                employee_email=identity.email,
                start_date=requested_start_date,
                position=current_job_title,
                work_location=current_work_location,
                status_change=current_status_change,
                submission_id=str(tracker_record.get("submission_id", "") or action_submission_id or "").strip(),
            )
            logger.info(
                "Draft card action create_envelope_draft result: employee=%s submission_id=%s success=%s envelope_id=%s",
                identity.email,
                str(tracker_record.get("submission_id", "") or action_submission_id or "").strip() or "<missing>",
                bool(draft_result.get("success")),
                str(draft_result.get("envelope_id", "") or "").strip() or "<missing>",
            )
            if not draft_result.get("success"):
                return {
                    "success": False,
                    "employee_email": identity.email,
                    "error": (
                        f"DocuSign draft creation failed for {identity.email}: "
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

        review_result = await docusign_client.create_envelope_edit_view(envelope_id)
        review_url = str(review_result.get("url", "") or "").strip()
        logger.info(
            "Draft card action edit view: employee=%s envelope_id=%s success=%s url_present=%s",
            identity.email,
            envelope_id,
            bool(review_result.get("success")),
            bool(review_url),
        )
        summary = "Offer letter draft created from the current tracker fields. Review the draft in DocuSign, then send it when ready."
        reply_card = docusign_status_card(
            employee_email=identity.email,
            envelope_id=envelope_id,
            status="created",
            summary=summary,
            submission_id=str(tracker_record.get("submission_id", "") or action_submission_id or "").strip(),
            employee_name=employee_name or identity.email,
            work_location=current_work_location,
            job_title=current_job_title,
            status_change=current_status_change,
            review_url=review_url,
            allow_send_action=True,
        )
        reply_result = await TeamsMessenger().send_channel_notification(
            channel_id=parent_card.get("channel_id", ""),
            message=summary,
            card=reply_card,
            session_context={
                "submission_id": str(tracker_record.get("submission_id", "") or action_submission_id or "").strip(),
                "employee_email": identity.email,
                "employee_name": employee_name or identity.email,
                "work_location": current_work_location,
                "job_title": current_job_title,
                "status_change": current_status_change,
                "intent": "send_docusign_envelope",
                "envelope_id": envelope_id,
            },
            reply_to_id=parent_card.get("message_id", ""),
        )
        logger.info(
            "Draft card action reply card send result: employee=%s submission_id=%s success=%s message_id=%s",
            identity.email,
            str(tracker_record.get("submission_id", "") or action_submission_id or "").strip() or "<missing>",
            bool(reply_result.get("success")),
            str(reply_result.get("message_id", "") or "").strip() or "<missing>",
        )
        if not reply_result.get("success"):
            return {
                "success": False,
                "employee_email": identity.email,
                "error": f"DocuSign draft created, but posting the review card failed: {reply_result.get('error', 'unknown error')}",
            }
        if not reply_result.get("message_id"):
            logger.warning(
                "DocuSign draft review card posted for %s without a returned Teams message_id; continuing without card update handle.",
                identity.email,
            )
        await save_docusign_status_card(
            employee_email=identity.email,
            employee_name=employee_name or identity.email,
            channel_id=parent_card.get("channel_id", ""),
            message_id=str(reply_result.get("message_id", "") or ""),
            envelope_id=envelope_id,
            status="created",
            summary=summary,
            submission_id=str(tracker_record.get("submission_id", "") or action_submission_id or ""),
            work_location=current_work_location,
            job_title=current_job_title,
            status_change=current_status_change,
            review_url=review_url,
            allow_send_action=True,
        )
        logger.info(
            "Draft card action completed successfully: employee=%s submission_id=%s envelope_id=%s",
            identity.email,
            str(tracker_record.get("submission_id", "") or action_submission_id or "").strip() or "<missing>",
            envelope_id,
        )
        return {
            "success": True,
            "employee_email": identity.email,
            "envelope_id": envelope_id,
            "status": "created",
            "review_url": review_url,
        }

    if action == "send_docusign":
        from onboarding_agent.integrations.docusign_client import DocuSignClient
        from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

        docusign_client = DocuSignClient()
        submission_id = action_submission_id or await _submission_id_for_identity(identity)
        docusign_card = await get_docusign_status_card(identity, submission_id=submission_id)
        envelope_id = str((docusign_card or {}).get("envelope_id", "") or "").strip()
        if not envelope_id:
            draft_result = await docusign_client.check_draft_exists(
                identity.email,
                identity.work_location,
                identity.job_title,
                identity.status_change,
            )
            envelope_id = str(draft_result.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": identity.email,
                "error": f"No DocuSign draft found for {identity.email}. Create the draft first.",
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
            submission_id=submission_id,
        )
        result: dict[str, Any] = dict(send_result)
        if not stage_result.get("success"):
            result["warning"] = f"Offer letter sent, but tracker update failed: {stage_result.get('error', 'unknown error')}"
        if docusign_card:
            await save_docusign_status_card(
                employee_email=identity.email,
                employee_name=str(docusign_card.get("employee_name", "") or identity.email),
                channel_id=docusign_card.get("channel_id", ""),
                message_id=docusign_card.get("message_id", ""),
                envelope_id=envelope_id,
                status="sent",
                summary="Offer letter sent to the employee via DocuSign.",
                submission_id=str(docusign_card.get("submission_id", "") or submission_id or ""),
                work_location=identity.work_location,
                job_title=identity.job_title,
                status_change=identity.status_change,
                roster_added=bool(docusign_card.get("roster_added", False)),
                job_category=str(docusign_card.get("job_category", "") or ""),
                review_url=str(docusign_card.get("review_url", "") or ""),
                allow_send_action=False,
            )
            await refresh_docusign_status_card(identity, submission_id=submission_id)
        return result

    if action == "refresh_review_link":
        from onboarding_agent.integrations.docusign_client import DocuSignClient

        submission_id = action_submission_id or await _submission_id_for_identity(identity)
        docusign_card = await get_docusign_status_card(identity, submission_id=submission_id)
        if not docusign_card:
            return {
                "success": False,
                "employee_email": identity.email,
                "error": f"No stored DocuSign status card found for {identity.email}.",
            }

        envelope_id = str(docusign_card.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": identity.email,
                "error": f"No DocuSign envelope is stored for {identity.email}.",
            }

        review_result = await DocuSignClient().create_envelope_edit_view(envelope_id)
        review_url = str(review_result.get("url", "") or "").strip()
        if not review_result.get("success") or not review_url:
            return {
                "success": False,
                "employee_email": identity.email,
                "error": (
                    f"Unable to refresh the review link for {identity.email}: "
                    f"{review_result.get('error', 'missing edit view URL')}"
                ),
            }

        await save_docusign_status_card(
            employee_email=identity.email,
            employee_name=str(docusign_card.get("employee_name", "") or identity.email),
            channel_id=docusign_card.get("channel_id", ""),
            message_id=docusign_card.get("message_id", ""),
            envelope_id=envelope_id,
            status=str(docusign_card.get("status", "") or "created"),
            summary=str(docusign_card.get("summary", "") or ""),
            submission_id=str(docusign_card.get("submission_id", "") or submission_id or ""),
            work_location=str(docusign_card.get("work_location", "") or identity.work_location or ""),
            job_title=str(docusign_card.get("job_title", "") or identity.job_title or ""),
            status_change=str(docusign_card.get("status_change", "") or identity.status_change or ""),
            roster_added=bool(docusign_card.get("roster_added", False)),
            job_category=str(docusign_card.get("job_category", "") or ""),
            review_url=review_url,
            allow_send_action=bool(docusign_card.get("allow_send_action", False)),
        )
        return {
            "success": True,
            "employee_email": identity.email,
            "envelope_id": envelope_id,
            "review_url": review_url,
        }

    return {"success": False, "employee_email": identity.email, "error": f"Unsupported card action: {action}"}


async def execute_new_hire_card_action_without_context(card_action: dict[str, str]) -> bool:
    identity = _identity_from_action(card_action)
    submission_id = str(card_action.get("submission_id", "") or "").strip()
    result = await _run_new_hire_card_action(card_action)
    if not result.get("success"):
        return False

    if card_action["action"] == "send_onboarding_email":
        await mark_new_hire_action_complete(identity, card_action["action"], submission_id=submission_id)
        refresh_result = await refresh_new_hire_card(identity, submission_id=submission_id)
        if not refresh_result.get("success"):
            return False
    elif card_action["action"] == "create_docusign_draft":
        await mark_new_hire_action_complete(identity, card_action["action"], submission_id=submission_id)
        refresh_result = await refresh_new_hire_card(identity, submission_id=submission_id)
        if not refresh_result.get("success"):
            logger.warning(
                "Offer letter draft action succeeded for %s, but root card refresh failed: %s",
                identity.email,
                refresh_result.get("error", "unknown error"),
            )
    elif card_action["action"] == "refresh_review_link":
        refresh_result = await refresh_docusign_status_card(identity, submission_id=submission_id)
        if not refresh_result.get("success"):
            return False

    warning = str(result.get("warning", "") or "").strip()
    if warning:
        card = await get_new_hire_card(identity, submission_id=submission_id)
        if card:
            await send_proactive_message(
                channel_id=card.get("channel_id", ""),
                message=warning,
            )
    return True


async def notify_card_action_failure(card_action: dict[str, str]) -> None:
    identity = _identity_from_action(card_action)
    submission_id = str(card_action.get("submission_id", "") or "").strip()
    card = await get_new_hire_card(identity, submission_id=submission_id)
    if not card:
        return

    action_labels = {
        "send_onboarding_email": "send the welcome email",
        "create_docusign_draft": "create the offer letter draft",
        "refresh_review_link": "refresh the review link",
        "send_docusign": "send the offer letter",
        "add_to_staff_roster": "add the employee to the staff roster",
    }
    action_label = action_labels.get(card_action["action"], "complete the requested action")
    if card_action["action"] in {"create_docusign_draft", "refresh_review_link"}:
        message = (
            f"The draft action could not refresh the original card for {identity.email}. "
            "Reply `Create the offer draft` to run the draft workflow directly."
        )
    else:
        message = f"Failed to {action_label} for {identity.email}. Check the agent logs for details."
    await send_proactive_message(
        channel_id=card.get("channel_id", ""),
        message=message,
    )


async def refresh_card_from_context(context: TurnContext, card_action: dict[str, str]) -> bool:
    identity = _identity_from_action(card_action)
    submission_id = str(card_action.get("submission_id", "") or "").strip()
    if card_action["action"] in {"add_to_staff_roster", "send_docusign", "create_docusign_draft", "refresh_review_link"}:
        card = await get_docusign_status_card(identity, submission_id=submission_id)
        if card:
            return await _update_docusign_status_card(context, card)
        if card_action["action"] not in {"create_docusign_draft", "refresh_review_link"}:
            return False
    card = await get_new_hire_card(identity, submission_id=submission_id)
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
        submission_id=card.get("submission_id", ""),
        title=card.get("title", ""),
        status_change=card.get("status_change", ""),
        requested_start_date=card.get("requested_start_date", ""),
        job_title=card.get("job_title", ""),
        work_location=card.get("work_location", ""),
        requesting_manager=card.get("requesting_manager", ""),
        summary=card.get("summary", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_draft_created=bool(card.get("docusign_draft_created")),
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
        submission_id=card.get("submission_id", ""),
        employee_name=card.get("employee_name", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
        work_location=card.get("work_location", ""),
        job_title=card.get("job_title", ""),
        status_change=card.get("status_change", ""),
        review_url=card.get("review_url", ""),
        allow_send_action=bool(card.get("allow_send_action", False)),
    )
    return await _update_card_via_context(context, card, updated, "DocuSign status")
