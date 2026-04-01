"""Background job handlers for webhook-driven onboarding work."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from onboarding_agent.config import settings
from onboarding_agent.domains.onboard.policies import (
    WORKFLOW_NEW_HIRE,
    WORKFLOW_REHIRE,
    excluded_stages_for,
    normalize_workflow_type,
)
from onboarding_agent.integrations.card_state import (
    reset_new_hire_card_actions,
    save_docusign_status_card,
    save_new_hire_card,
)
from onboarding_agent.integrations.docusign_client import DocuSignClient
from onboarding_agent.integrations.teams.messenger import TeamsMessenger
from onboarding_agent.integrations.tracker_client import TrackerClient
from onboarding_agent.mcp_server.tools_email import draft_onboarding_email_for_employee
from onboarding_agent.runtime.job_queue import QueueJob

logger = logging.getLogger(__name__)

JOB_NEW_HIRE = "new_hire_webhook"
JOB_DOCUSIGN = "docusign_webhook"
JOB_BACKGROUND_CLEARANCE = "background_clearance_webhook"


def _notification_channel() -> str:
    return settings.notification_channel()


def _payload_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _payload_any(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            value = payload.get(key)
            if value not in (None, ""):
                return value
    return ""


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
        name = str(entry.get("name", "") or "").strip()
        if link and name:
            links.append(f"{name}: {link}")
        elif link:
            links.append(link)
        elif name:
            links.append(name)
    return " | ".join(links)


def _new_hire_fields(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "requesting_manager": _payload_value(payload, "requestingManager"),
        "work_location": _payload_value(payload, "workLocation"),
        "status_change": _payload_value(payload, "statusChange"),
        "staff_name": _payload_value(payload, "staffName"),
        "staff_email": _payload_value(payload, "staffEmail"),
        "staff_phone": _payload_value(payload, "staffPhone"),
        "job_title": _payload_value(payload, "jobTitle"),
        "requested_start_date": _payload_value(payload, "requestedStartDate"),
        "education_level": _payload_value(payload, "educationLevel"),
        "supplements": _payload_value(payload, "supplements"),
        "license_number": _payload_value(payload, "licenseNumber"),
        "uploaded_credentials": _uploaded_credentials_value(
            _payload_any(
                payload,
                "uploadedCredentials",
            )
        ),
        "compensation": _payload_value(payload, "compensation"),
        "employment_type": _payload_value(payload, "employmentType"),
        "contract_term": _payload_value(payload, "contractTerm"),
    }


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


async def process_new_hire_job(payload: dict[str, Any]) -> None:
    """Handle HR-submission webhook work deterministically by workflow type."""
    workflow_type = normalize_workflow_type(_payload_value(payload, "statusChange"))
    if workflow_type == WORKFLOW_NEW_HIRE:
        await _process_new_hire_submission(payload)
        return
    await _process_non_new_hire_submission(payload, workflow_type)


async def _process_new_hire_submission(payload: dict[str, Any]) -> None:
    """Handle new-hire workflow deterministically."""
    from onboarding_agent.integrations.adaptive_cards import new_hire_card

    started = time.perf_counter()
    tracker_client = TrackerClient()
    docusign_client = DocuSignClient()
    teams_messenger = TeamsMessenger()

    fields = _new_hire_fields(payload)
    employee_email = fields["staff_email"].strip()
    employee_name = fields["staff_name"].strip()
    if not employee_email:
        raise ValueError("New-hire payload missing employee email")
    if not fields["work_location"].strip() or not fields["job_title"].strip():
        raise ValueError("New-hire payload must include workLocation and jobTitle for composite identity")

    try:
        tracker_result = await tracker_client.find_employee_in_tracker(
            employee_email,
            location=fields["work_location"],
            job_title=fields["job_title"],
        )
        tracker_text = ""
        if tracker_result.get("found"):
            tracker_text = "Tracker record already exists."
        elif tracker_result.get("multiple_matches"):
            tracker_text = (
                "Tracker lookup found multiple rows for this email. "
                "Skipped tracker write; add location and position disambiguation in the payload."
            )
        else:
            add_result = await tracker_client.add_employee_to_tracker(**fields)
            tracker_text = (
                f"Added to tracker (row {add_result.get('row_id', '?')})."
                if add_result.get("success")
                else f"Tracker write failed: {add_result.get('error', 'unknown error')}."
            )

        draft_result = await docusign_client.check_draft_exists(employee_email)
        docusign_text = ""
        if draft_result.get("exists"):
            docusign_text = f"DocuSign draft already exists ({draft_result.get('envelope_id', '')[:8]}...)."
        else:
            create_result = await docusign_client.create_envelope_draft(
                employee_name=employee_name or employee_email,
                employee_email=employee_email,
                start_date=fields["requested_start_date"],
                position=fields["job_title"],
            )
            docusign_text = (
                f"DocuSign draft created ({str(create_result.get('envelope_id', ''))[:8]}...)."
                if create_result.get("success")
                else f"DocuSign draft creation failed: {create_result.get('error', 'unknown error')}."
            )

        email_result = await draft_onboarding_email_for_employee(
            employee_email=employee_email,
            employee_name=employee_name or employee_email,
        )
        email_text = (
            "Welcome email drafted for HR review."
            if email_result.get("success")
            else f"Welcome email draft failed: {email_result.get('error', 'unknown error')}."
        )

        summary = " ".join([tracker_text, docusign_text, email_text]).strip()
        await reset_new_hire_card_actions(employee_email)
        card = new_hire_card(
            employee_name=employee_name or employee_email,
            employee_email=employee_email,
            summary=summary,
            status_change=fields["status_change"],
            requested_start_date=fields["requested_start_date"],
            job_title=fields["job_title"],
            work_location=fields["work_location"],
            requesting_manager=fields["requesting_manager"],
            email_sent=False,
            docusign_sent=False,
        )
        teams_result = await teams_messenger.send_channel_notification(
            _notification_channel(),
            summary,
            card=card,
        )
        if teams_result.get("success") and teams_result.get("message_id"):
            await save_new_hire_card(
                employee_email=employee_email,
                channel_id=_notification_channel(),
                message_id=str(teams_result["message_id"]),
                employee_name=employee_name or employee_email,
                status_change=fields["status_change"],
                requested_start_date=fields["requested_start_date"],
                job_title=fields["job_title"],
                work_location=fields["work_location"],
                requesting_manager=fields["requesting_manager"],
                summary=summary,
            )
        if not teams_result.get("success"):
            raise RuntimeError(f"Teams notification failed: {teams_result.get('error', 'unknown error')}")

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
    from onboarding_agent.integrations.adaptive_cards import new_hire_card

    started = time.perf_counter()
    tracker_client = TrackerClient()
    docusign_client = DocuSignClient()
    teams_messenger = TeamsMessenger()
    fields = _new_hire_fields(payload)

    employee_email = fields["staff_email"].strip()
    employee_name = fields["staff_name"].strip()
    if not employee_email:
        raise ValueError("HR-submission payload missing employee email")
    if not fields["work_location"].strip() or not fields["job_title"].strip():
        raise ValueError("HR-submission payload must include workLocation and jobTitle for composite identity")

    workflow_label = workflow_type.replace("_", " ").title()
    try:
        tracker_result = await tracker_client.find_employee_in_tracker(
            employee_email,
            location=fields["work_location"],
            job_title=fields["job_title"],
        )
        if tracker_result.get("found"):
            tracker_text = "Tracker record already exists."
        elif tracker_result.get("multiple_matches"):
            tracker_text = (
                "Tracker lookup found multiple rows for this email. "
                "Skipped tracker write; add location and position disambiguation in the payload."
            )
        else:
            add_result = await tracker_client.add_employee_to_tracker(**fields)
            tracker_text = (
                f"Added to tracker (row {add_result.get('row_id', '?')})."
                if add_result.get("success")
                else f"Tracker write failed: {add_result.get('error', 'unknown error')}."
            )

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
                )
                if stage_result.get("success"):
                    stage_results.append(stage_name)
            if stage_results:
                policy_text = (
                    f" {workflow_label} workflow applied: marked non-applicable stages as N/A: "
                    + ", ".join(stage_results)
                    + "."
                )

        draft_result = await docusign_client.check_draft_exists(employee_email)
        docusign_text = ""
        if draft_result.get("exists"):
            docusign_text = f" DocuSign draft already exists ({draft_result.get('envelope_id', '')[:8]}...)."
        else:
            create_result = await docusign_client.create_envelope_draft(
                employee_name=employee_name or employee_email,
                employee_email=employee_email,
                start_date=fields["requested_start_date"],
                position=fields["job_title"],
            )
            docusign_text = (
                f" DocuSign draft created ({str(create_result.get('envelope_id', ''))[:8]}...)."
                if create_result.get("success")
                else f" DocuSign draft creation failed: {create_result.get('error', 'unknown error')}."
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
            f"{tracker_text}{policy_text}{docusign_text}{email_text} This workflow is running in deterministic mode."
        )
        if workflow_type == WORKFLOW_REHIRE:
            await reset_new_hire_card_actions(employee_email)
            card = new_hire_card(
                employee_name=employee_name or employee_email,
                employee_email=employee_email,
                summary=summary,
                status_change=fields["status_change"],
                requested_start_date=fields["requested_start_date"],
                job_title=fields["job_title"],
                work_location=fields["work_location"],
                requesting_manager=fields["requesting_manager"],
                email_sent=False,
                docusign_sent=False,
                allow_email_action=True,
                allow_docusign_action=True,
            )
            teams_result = await teams_messenger.send_channel_notification(
                _notification_channel(),
                summary,
                card=card,
            )
            if teams_result.get("success") and teams_result.get("message_id"):
                await save_new_hire_card(
                    employee_email=employee_email,
                    channel_id=_notification_channel(),
                    message_id=str(teams_result["message_id"]),
                    employee_name=employee_name or employee_email,
                    status_change=fields["status_change"],
                    requested_start_date=fields["requested_start_date"],
                    job_title=fields["job_title"],
                    work_location=fields["work_location"],
                    requesting_manager=fields["requesting_manager"],
                    summary=summary,
                    allow_email_action=True,
                    allow_docusign_action=True,
                )
        else:
            teams_result = await teams_messenger.send_channel_notification(_notification_channel(), summary)
        if not teams_result.get("success"):
            raise RuntimeError(f"Teams notification failed: {teams_result.get('error', 'unknown error')}")
        logger.info(
            "Processed queued %s job for %s in %.3fs",
            workflow_type,
            employee_email or "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued %s job failed for %s", workflow_type, employee_email or "unknown")
        raise


async def process_docusign_job(payload: dict[str, Any]) -> None:
    """Handle DocuSign status webhook work deterministically."""
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card

    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()
    docusign_client = DocuSignClient()

    envelope_id = str(payload.get("envelope_id", "")).strip()
    status = str(payload.get("status", "")).strip().lower()
    employee_email = str(payload.get("employee_email", "")).strip().lower()
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
            stage_result = await tracker_client.update_stage(employee_email, "Offer Letter Signed")
        elif employee_email and status == "sent":
            stage_result = await tracker_client.update_stage(employee_email, "Sent Offer Letter")

        stage_text = (
            "Tracker stage updated successfully."
            if stage_result.get("success")
            else f"Tracker stage update not applied: {stage_result.get('error', 'unknown error')}."
        )
        summary = (
            f"DocuSign envelope {envelope_id[:8]}... changed to {status}. "
            f"Employee: {employee_email or 'unknown'}. {stage_text}"
        )
        card = docusign_status_card(employee_email, envelope_id, status, summary)
        teams_result = await teams_messenger.send_channel_notification(
            _notification_channel(),
            summary,
            card=card,
        )
        if status == "completed" and teams_result.get("success") and teams_result.get("message_id") and employee_email:
            await save_docusign_status_card(
                employee_email=employee_email,
                channel_id=_notification_channel(),
                message_id=str(teams_result["message_id"]),
                envelope_id=envelope_id,
                status=status,
                summary=summary,
            )
        if not teams_result.get("success"):
            raise RuntimeError(f"Teams notification failed: {teams_result.get('error', 'unknown error')}")
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

    employee_email = str(payload.get("employeeEmail", "")).strip()
    employee_name = str(payload.get("employeeName", "")).strip()
    if not employee_email:
        raise ValueError("Background-clearance payload missing employeeEmail")

    started = time.perf_counter()
    tracker_client = TrackerClient()
    teams_messenger = TeamsMessenger()

    try:
        stage_result = await tracker_client.update_stage(employee_email, "Background Submission")

        stage_text = (
            f"Tracker updated: Background Submission on {stage_result.get('value', '')}."
            if stage_result.get("success")
            else f"Tracker update failed: {stage_result.get('error', 'unknown error')}."
        )
        summary = (
            f"{employee_name or employee_email} ({employee_email}) submitted the background clearance form. "
            f"{stage_text} A confirmation email has been requested."
        )
        card = background_clearance_card(employee_name or employee_email, employee_email, summary)
        teams_result = await teams_messenger.send_channel_notification(
            _notification_channel(),
            summary,
            card=card,
        )
        email_result = await send_background_clearance_confirmation_email(employee_email, employee_name or employee_email)

        logger.info(
            "Processed background-clearance job for %s stage_success=%s teams_success=%s email_success=%s in %.3fs",
            employee_email or "unknown",
            stage_result.get("success", False),
            teams_result.get("success", False),
            email_result.get("success", False),
            time.perf_counter() - started,
        )

        if not teams_result.get("success"):
            raise RuntimeError(f"Teams notification failed: {teams_result.get('error', 'unknown error')}")
        if not email_result.get("success"):
            raise RuntimeError(f"Confirmation email failed: {email_result.get('error', 'unknown error')}")
        logger.info(
            "Processed queued background-clearance job for %s in %.3fs",
            employee_email or "unknown",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued background-clearance job failed for %s", employee_email or "unknown")
        raise
