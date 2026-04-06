"""Background job handlers for webhook-driven onboarding work."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from onboarding_agent.config import settings
from onboarding_agent.domain.identity import EmployeeIdentity
from onboarding_agent.domain.onboard.policies import (
    WORKFLOW_LEAVE_START,
    WORKFLOW_NEW_HIRE,
    WORKFLOW_REHIRE,
    WORKFLOW_SECOND_POSITION,
    excluded_stages_for,
    is_leave_workflow,
    is_separation_workflow,
    is_separations_sheet_workflow,
    normalize_workflow_type,
)
from onboarding_agent.integrations.card_state import (
    _submission_card_title,
    reset_new_hire_card_actions,
    save_docusign_status_card,
    save_new_hire_card,
    save_separation_card,
)
from onboarding_agent.integrations.docusign_client import DocuSignClient
from onboarding_agent.integrations.teams.messenger import TeamsMessenger
from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient
from onboarding_agent.mcp_server.tools_email import draft_onboarding_email_for_employee
from onboarding_agent.runtime.job_queue import QueueJob
from onboarding_agent.runtime.payloads import payload_any, payload_value

logger = logging.getLogger(__name__)

JOB_NEW_HIRE = "new_hire_webhook"
JOB_DOCUSIGN = "docusign_webhook"
JOB_BACKGROUND_CLEARANCE = "background_clearance_webhook"


def _notification_channel() -> str:
    return settings.notification_channel()


def _employee_thread_context(
    *,
    submission_id: str = "",
    employee_email: str,
    employee_name: str = "",
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
    intent: str = "",
    envelope_id: str = "",
) -> dict[str, str]:
    context = {
        "submission_id": submission_id,
        "employee_email": employee_email,
        "employee_name": employee_name,
        "work_location": work_location,
        "job_title": job_title,
        "status_change": status_change,
        "intent": intent,
        "envelope_id": envelope_id,
    }
    return {key: value for key, value in context.items() if value}


def _uploaded_credentials_value(raw_value: Any) -> str:
    if isinstance(raw_value, list):
        entries = raw_value
    elif isinstance(raw_value, dict):
        entries = [raw_value]
    else:
        text = str(raw_value or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, list):
            entries = parsed
        elif isinstance(parsed, dict):
            entries = [parsed]
        else:
            return text

    links: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        link = str(entry.get("link", "") or "").strip()
        if link:
            links.append(link)
    return " ".join(links)


def _new_hire_fields(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "submission_id": payload_value(payload, "submissionId"),
        "requesting_manager": payload_value(payload, "requestingManager"),
        "work_location": payload_value(payload, "workLocation"),
        "status_change": payload_value(payload, "statusChange"),
        "staff_name": payload_value(payload, "staffName"),
        "staff_email": payload_value(payload, "staffEmail"),
        "staff_phone": payload_value(payload, "staffPhone"),
        "job_title": payload_value(payload, "jobTitle"),
        "requested_start_date": payload_value(payload, "requestedStartDate"),
        "education_level": payload_value(payload, "educationLevel"),
        "supplements": payload_value(payload, "supplements"),
        "license_number": payload_value(payload, "licenseNumber"),
        "uploaded_credentials": _uploaded_credentials_value(
            payload_any(
                payload,
                "uploadedCredentials",
            )
        ),
        "compensation": payload_value(payload, "compensation"),
        "employment_type": payload_value(payload, "employmentType"),
        "contract_term": payload_value(payload, "contractTerm"),
    }


def _require_composite_identity(fields: dict[str, str], *, label: str) -> None:
    if not fields["staff_email"].strip():
        raise ValueError(f"{label} payload missing employee email")
    if not fields["work_location"].strip() or not fields["job_title"].strip():
        raise ValueError(f"{label} payload must include workLocation and jobTitle for composite identity")


async def _send_or_raise(
    teams_messenger: TeamsMessenger,
    *,
    summary: str,
    card: dict[str, Any],
    session_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = await teams_messenger.send_channel_notification(
        _notification_channel(),
        summary,
        card=card,
        session_context=session_context,
    )
    if not result.get("success"):
        raise RuntimeError(f"Teams notification failed: {result.get('error', 'unknown error')}")
    return result


async def _send_submission_notification(
    teams_messenger: TeamsMessenger,
    *,
    employee_email: str,
    employee_name: str,
    fields: dict[str, str],
    summary: str,
    allow_email_action: bool,
) -> None:
    from onboarding_agent.integrations.adaptive_cards import new_hire_card

    await reset_new_hire_card_actions(EmployeeIdentity(
        email=employee_email,
        work_location=fields["work_location"],
        job_title=fields["job_title"],
        status_change=fields["status_change"],
    ))
    card = new_hire_card(
        employee_name=employee_name or employee_email,
        employee_email=employee_email,
        summary=summary,
        submission_id=fields["submission_id"],
        title=_submission_card_title(fields["status_change"]),
        status_change=fields["status_change"],
        requested_start_date=fields["requested_start_date"],
        job_title=fields["job_title"],
        work_location=fields["work_location"],
        requesting_manager=fields["requesting_manager"],
        email_sent=False,
        docusign_draft_created=False,
        allow_email_action=allow_email_action,
        allow_docusign_action=True,
    )
    teams_result = await _send_or_raise(
        teams_messenger,
        summary=summary,
        card=card,
        session_context=_employee_thread_context(
            submission_id=fields["submission_id"],
            employee_email=employee_email,
            employee_name=employee_name or employee_email,
            work_location=fields["work_location"],
            job_title=fields["job_title"],
            status_change=fields["status_change"],
            intent="check_onboarding_status",
        ),
    )
    if teams_result.get("message_id"):
        await save_new_hire_card(
            employee_email=employee_email,
            channel_id=_notification_channel(),
            message_id=str(teams_result["message_id"]),
            submission_id=fields["submission_id"],
            employee_name=employee_name or employee_email,
            title=_submission_card_title(fields["status_change"]),
            status_change=fields["status_change"],
            requested_start_date=fields["requested_start_date"],
            job_title=fields["job_title"],
            work_location=fields["work_location"],
            requesting_manager=fields["requesting_manager"],
            summary=summary,
            allow_email_action=allow_email_action,
            allow_docusign_action=True,
        )


async def process_job(job: QueueJob) -> None:
    """Dispatch a queued job to its concrete handler."""
    if job.job_type == JOB_NEW_HIRE:
        await process_new_hire_job(job.payload)
        return
    if job.job_type == JOB_DOCUSIGN:
        await process_docusign_job(job.payload)
        return
    if job.job_type == JOB_BACKGROUND_CLEARANCE:
        await process_background_clearance_job(job.payload)
        return
    raise ValueError(f"Unsupported job type: {job.job_type}")


async def _ensure_tracker_record(
    tracker_client: TrackerClient, fields: dict[str, str],
) -> str:
    """Look up or create a tracker row. Returns a summary sentence."""
    result = await tracker_client.find_employee_in_tracker(
        fields["staff_email"],
        location=fields["work_location"],
        job_title=fields["job_title"],
        status_change=fields["status_change"],
        submission_id=fields["submission_id"],
    )
    if result.get("found"):
        return "Tracker record already exists."
    if result.get("multiple_matches"):
        return (
            "Tracker lookup found multiple rows for this email. "
            "Skipped tracker write; add location and position disambiguation in the payload."
        )
    add_result = await tracker_client.add_employee_to_tracker(**fields)
    if add_result.get("success"):
        return f"Added to tracker (row {add_result.get('row_id', '?')})."
    return f"Tracker write failed: {add_result.get('error', 'unknown error')}."


async def process_new_hire_job(payload: dict[str, Any]) -> None:
    """Handle HR-submission webhook work deterministically by workflow type."""
    workflow_type = normalize_workflow_type(payload_value(payload, "statusChange"))
    if workflow_type == WORKFLOW_NEW_HIRE:
        await _process_new_hire_submission(payload)
        return
    if is_separation_workflow(workflow_type):
        await _process_separation_submission(payload, workflow_type)
        return
    await _process_non_new_hire_submission(payload, workflow_type)


async def _process_new_hire_submission(payload: dict[str, Any]) -> None:
    """Handle new-hire workflow deterministically."""
    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()

    fields = _new_hire_fields(payload)
    employee_email = fields["staff_email"].strip()
    employee_name = fields["staff_name"].strip()
    _require_composite_identity(fields, label="New-hire")

    try:
        tracker_text = await _ensure_tracker_record(tracker_client, fields)
        email_result = await draft_onboarding_email_for_employee(
            employee_email=employee_email,
            employee_name=employee_name or employee_email,
        )
        email_text = (
            "Welcome email drafted for HR review."
            if email_result.get("success")
            else f"Welcome email draft failed: {email_result.get('error', 'unknown error')}."
        )

        summary = " ".join(
            [tracker_text, "Offer letter draft can be created from the current tracker fields.", email_text]
        ).strip()
        await _send_submission_notification(
            teams_messenger,
            employee_email=employee_email,
            employee_name=employee_name,
            fields=fields,
            summary=summary,
            allow_email_action=True,
        )

        logger.info(
            "Processed queued new-hire job for %s in %.3fs",
            employee_email or "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued new-hire job failed for %s", employee_email or "unknown")
        raise


async def _process_non_new_hire_submission(payload: dict[str, Any], workflow_type: str) -> None:
    """Handle non-new-hire HR workflows deterministically (no LLM orchestration)."""
    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()
    fields = _new_hire_fields(payload)

    employee_email = fields["staff_email"].strip()
    employee_name = fields["staff_name"].strip()
    _require_composite_identity(fields, label="HR-submission")

    workflow_label = workflow_type.replace("_", " ").title()
    try:
        tracker_text = await _ensure_tracker_record(tracker_client, fields)

        excluded_stages = excluded_stages_for(workflow_type)

        policy_text = ""
        if excluded_stages:
            stage_results: list[str] = []
            for stage_name in excluded_stages:
                stage_result = await tracker_client.update_stage(
                    employee_email,
                    stage_name,
                    value="N/A",
                    location=fields["work_location"],
                    job_title=fields["job_title"],
                    status_change=fields["status_change"],
                    submission_id=fields["submission_id"],
                )
                if stage_result.get("success"):
                    stage_results.append(stage_name)
            if stage_results:
                policy_text = (
                    f" {workflow_label} workflow applied: marked non-applicable stages as N/A: "
                    + ", ".join(stage_results)
                    + "."
                )

        email_text = ""
        if workflow_type == WORKFLOW_REHIRE:
            email_result = await draft_onboarding_email_for_employee(
                employee_email=employee_email,
                employee_name=employee_name or employee_email,
            )
            email_text = (
                " Welcome email drafted for HR review."
                if email_result.get("success")
                else f" Welcome email draft failed: {email_result.get('error', 'unknown error')}."
            )

        summary = (
            f"{workflow_label} submission received for {employee_name or employee_email} ({employee_email}). "
            f"{tracker_text}{policy_text} Offer letter draft can be created from the current tracker fields.{email_text} This workflow is running in deterministic mode."
        )
        allow_email_action = workflow_type in {WORKFLOW_NEW_HIRE, WORKFLOW_REHIRE}
        await _send_submission_notification(
            teams_messenger,
            employee_email=employee_email,
            employee_name=employee_name,
            fields=fields,
            summary=summary,
            allow_email_action=allow_email_action,
        )
        logger.info(
            "Processed queued %s job for %s in %.3fs",
            workflow_type,
            employee_email or "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued %s job failed for %s", workflow_type, employee_email or "unknown")
        raise


async def _process_separation_submission(payload: dict[str, Any], workflow_type: str) -> None:
    """Handle separation-category workflows deterministically (no LLM)."""
    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()
    fields = _new_hire_fields(payload)

    employee_email = fields["staff_email"].strip()
    employee_name = fields["staff_name"].strip()
    _require_composite_identity(fields, label="Separation")

    workflow_label = workflow_type.replace("_", " ").title()
    try:
        tracker_text = await _ensure_tracker_record(tracker_client, fields)

        excluded_stages = excluded_stages_for(workflow_type)
        policy_text = ""
        if excluded_stages:
            stage_results: list[str] = []
            for stage_name in excluded_stages:
                stage_result = await tracker_client.update_stage(
                    employee_email,
                    stage_name,
                    value="N/A",
                    location=fields["work_location"],
                    job_title=fields["job_title"],
                    status_change=fields["status_change"],
                    submission_id=fields["submission_id"],
                )
                if stage_result.get("success"):
                    stage_results.append(stage_name)
            if stage_results:
                policy_text = (
                    f" {workflow_label} workflow applied: marked non-applicable stages as N/A: "
                    + ", ".join(stage_results)
                    + "."
                )

        # Determine action button for the card
        if is_separations_sheet_workflow(workflow_type):
            action_name = "record_separation"
            action_label = "Record on Separations Sheet"
            action_completed_label = "\u2713 Recorded on Separations Sheet"
            instruction = "Record on the Separations sheet using the button below."
        elif is_leave_workflow(workflow_type):
            if workflow_type == WORKFLOW_LEAVE_START:
                action_name = "update_leave_start"
                action_label = "Mark On Leave"
                action_completed_label = "\u2713 Marked On Leave"
                instruction = "Update the staff roster leave status using the button below."
            else:
                action_name = "update_leave_end"
                action_label = "Mark Active"
                action_completed_label = "\u2713 Marked Active"
                instruction = "Update the staff roster leave status using the button below."
        elif workflow_type == WORKFLOW_SECOND_POSITION:
            action_name = "add_to_staff_roster"
            action_label = "Add to Staff Roster"
            action_completed_label = "\u2713 Added to Staff Roster"
            instruction = "Add the employee to the staff roster using the button below."
        else:
            action_name = ""
            action_label = ""
            action_completed_label = ""
            instruction = ""

        summary = (
            f"{workflow_label} submission received for {employee_name or employee_email} "
            f"({employee_email}). {tracker_text}{policy_text}"
            f" {instruction} This workflow is running in deterministic mode."
        )
        await _send_separation_notification(
            teams_messenger,
            employee_email=employee_email,
            employee_name=employee_name,
            fields=fields,
            summary=summary,
            action_name=action_name,
            action_label=action_label,
            action_completed_label=action_completed_label,
        )
        logger.info(
            "Processed queued %s job for %s in %.3fs",
            workflow_type,
            employee_email or "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued %s job failed for %s", workflow_type, employee_email or "unknown")
        raise


async def _send_separation_notification(
    teams_messenger: TeamsMessenger,
    *,
    employee_email: str,
    employee_name: str,
    fields: dict[str, str],
    summary: str,
    action_name: str = "",
    action_label: str = "",
    action_completed_label: str = "",
) -> None:
    from onboarding_agent.integrations.adaptive_cards import separation_card

    card = separation_card(
        employee_name=employee_name or employee_email,
        employee_email=employee_email,
        summary=summary,
        submission_id=fields["submission_id"],
        title=_submission_card_title(fields["status_change"]),
        status_change=fields["status_change"],
        requested_start_date=fields["requested_start_date"],
        job_title=fields["job_title"],
        work_location=fields["work_location"],
        requesting_manager=fields["requesting_manager"],
        action_name=action_name,
        action_label=action_label,
        action_completed_label=action_completed_label,
    )
    teams_result = await _send_or_raise(
        teams_messenger,
        summary=summary,
        card=card,
        session_context=_employee_thread_context(
            submission_id=fields["submission_id"],
            employee_email=employee_email,
            employee_name=employee_name or employee_email,
            work_location=fields["work_location"],
            job_title=fields["job_title"],
            status_change=fields["status_change"],
            intent="check_onboarding_status",
        ),
    )
    if teams_result.get("message_id"):
        await save_separation_card(
            employee_email=employee_email,
            channel_id=_notification_channel(),
            message_id=str(teams_result["message_id"]),
            submission_id=fields["submission_id"],
            employee_name=employee_name or employee_email,
            title=_submission_card_title(fields["status_change"]),
            status_change=fields["status_change"],
            requested_start_date=fields["requested_start_date"],
            job_title=fields["job_title"],
            work_location=fields["work_location"],
            requesting_manager=fields["requesting_manager"],
            summary=summary,
            action_name=action_name,
            action_label=action_label,
            action_completed_label=action_completed_label,
        )


async def process_docusign_job(payload: dict[str, Any]) -> None:
    """Handle DocuSign status webhook work deterministically."""
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card

    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()
    docusign_client = DocuSignClient()
    staff_roster_client = StaffRosterClient()

    envelope_id = str(payload.get("envelope_id", "")).strip()
    status = str(payload.get("status", "")).strip().lower()
    employee_email = str(payload.get("employee_email", "")).strip().lower()
    work_location = str(payload.get("work_location", "")).strip()
    job_title = str(payload.get("job_title", "")).strip()
    status_change = str(payload.get("status_change", "")).strip()
    submission_id = str(payload.get("submission_id", "")).strip()
    if not envelope_id:
        raise ValueError("DocuSign payload missing envelope_id")
    if not status:
        raise ValueError("DocuSign payload missing status")

    if not employee_email:
        status_result = await docusign_client.get_envelope_status(envelope_id)
        recipients = status_result.get("recipients", [])
        if isinstance(recipients, list) and recipients:
            employee_email = str(recipients[0].get("email", "")).strip().lower()

    try:
        stage_result: dict[str, Any] = {"success": False, "error": "No tracker stage update required"}
        if employee_email and status == "completed":
            stage_result = await tracker_client.update_stage(
                employee_email,
                "Offer Letter Signed",
                location=work_location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
        elif employee_email and status == "sent":
            stage_result = await tracker_client.update_stage(
                employee_email,
                "Sent Offer Letter",
                location=work_location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )

        stage_text = (
            "Tracker stage updated successfully."
            if stage_result.get("success")
            else f"Tracker stage update not applied: {stage_result.get('error', 'unknown error')}."
        )
        summary = (
            f"DocuSign envelope {envelope_id[:8]}... changed to {status}. "
            f"Employee: {employee_email or 'unknown'}. {stage_text}"
        )
        roster_added = False
        roster_job_category = ""
        if status == "completed" and employee_email:
            tracker_record = await tracker_client.find_employee_in_tracker(
                employee_email,
                location=work_location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            roster_state = await staff_roster_client.find_employee_in_staff_roster(
                employee_email,
                location=work_location,
                personal_email=employee_email,
                employee_name=str(tracker_record.get("name", "") or ""),
                position=str(tracker_record.get("position", "") or tracker_record.get("job_title", "") or job_title),
            )
            roster_added = bool(roster_state.get("found"))
            roster_job_category = str(roster_state.get("job_category", "") or "")
        card = docusign_status_card(
            employee_email,
            envelope_id,
            status,
            summary,
            employee_name=str(tracker_record.get("name", "") or employee_email) if status == "completed" and employee_email else employee_email,
            roster_added=roster_added,
            job_category=roster_job_category,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
        teams_result = await _send_or_raise(
            teams_messenger,
            summary=summary,
            card=card,
            session_context=_employee_thread_context(
                submission_id=submission_id,
                employee_email=employee_email,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
                intent="check_onboarding_status",
                envelope_id=envelope_id,
            ),
        )
        if status == "completed" and teams_result.get("message_id") and employee_email:
            await save_docusign_status_card(
                employee_email=employee_email,
                employee_name=str(tracker_record.get("name", "") or employee_email) if employee_email else "",
                channel_id=_notification_channel(),
                message_id=str(teams_result["message_id"]),
                envelope_id=envelope_id,
                status=status,
                summary=summary,
                submission_id=submission_id,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
                roster_added=roster_added,
                job_category=roster_job_category,
            )
        logger.info(
            "Processed queued DocuSign job for %s in %.3fs",
            envelope_id[:8] if envelope_id else "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued DocuSign job failed for %s", envelope_id[:8] if envelope_id else "unknown")
        raise


async def process_background_clearance_job(payload: dict[str, Any]) -> None:
    """Handle background-clearance webhook work deterministically."""
    from onboarding_agent.integrations.adaptive_cards import background_clearance_card
    from onboarding_agent.mcp_server.tools_email import send_background_clearance_confirmation_email

    employee_email = payload_value(payload, "staffEmail", "employeeEmail")
    employee_name = payload_value(payload, "staffName", "employeeName")
    work_location = str(payload.get("workLocation", "")).strip()
    job_title = str(payload.get("jobTitle", "")).strip()
    status_change = str(payload.get("statusChange", "")).strip()
    if not employee_email:
        raise ValueError("Background-clearance payload missing staffEmail")

    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()

    try:
        tracker_record = await tracker_client.find_employee_in_tracker(
            employee_email,
            location=work_location,
            job_title=job_title,
            status_change=status_change,
        )
        resolved_employee_name = str(tracker_record.get("name", "") or employee_name or employee_email)

        stage_result = await tracker_client.update_stage(
            employee_email,
            "Background Submission",
            location=work_location,
            job_title=job_title,
            status_change=status_change,
        )

        stage_text = (
            f"Tracker updated: Background Submission on {stage_result.get('value', '')}."
            if stage_result.get("success")
            else f"Tracker update failed: {stage_result.get('error', 'unknown error')}."
        )
        summary = (
            f"{resolved_employee_name} ({employee_email}) submitted the background clearance form. "
            f"{stage_text} A confirmation email has been requested."
        )
        card = background_clearance_card(
            resolved_employee_name,
            employee_email,
            summary,
            work_location=work_location,
            job_title=job_title,
        )
        teams_result = await _send_or_raise(
            teams_messenger,
            summary=summary,
            card=card,
            session_context=_employee_thread_context(
                employee_email=employee_email,
                employee_name=resolved_employee_name,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
                intent="background_clearance",
            ),
        )
        email_result = await send_background_clearance_confirmation_email(employee_email, resolved_employee_name)

        if not email_result.get("success"):
            logger.warning(
                "Background-clearance confirmation email failed for %s: %s",
                employee_email or "unknown",
                email_result.get("error", "unknown error"),
            )
        logger.info(
            "Processed background-clearance job for %s stage_success=%s teams_success=%s email_success=%s in %.3fs",
            employee_email or "unknown",
            stage_result.get("success", False),
            teams_result.get("success", False),
            email_result.get("success", False),
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued background-clearance job failed for %s", employee_email or "unknown")
        raise
