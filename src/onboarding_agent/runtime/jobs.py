"""Background job handlers for webhook-driven onboarding work."""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from onboarding_agent.agent.runner import run_agent
from onboarding_agent.config import settings
from onboarding_agent.integrations.teams.messenger import TeamsMessenger
from onboarding_agent.integrations.tracker_client import TrackerClient
from onboarding_agent.runtime.job_queue import QueueJob

logger = logging.getLogger(__name__)

JOB_NEW_HIRE = "new_hire_webhook"
JOB_DOCUSIGN = "docusign_webhook"
JOB_BACKGROUND_CLEARANCE = "background_clearance_webhook"


def _notification_channel() -> str:
    return settings.notification_channel()


def _new_hire_prompt(payload: dict[str, Any]) -> str:
    employee_name = payload.get("employeeName", "")
    employee_email = payload.get("employeeEmail", "")
    start_date = payload.get("startDate", "")
    department = payload.get("department", "")
    location = payload.get("location", "")
    manager_email = payload.get("managerEmail", "")
    channel = _notification_channel()

    return (
        f"A new hire has been submitted via Microsoft Forms. "
        f"Employee: {employee_name} ({employee_email}), "
        f"Start date: {start_date}, "
        f"Department: {department}, "
        f"Location: {location}, "
        f"Manager: {manager_email}. "
        "Please run the onboarding pipeline: "
        "1) Check if employee is already in the tracker; if not, add them. "
        "2) Check if a DocuSign draft already exists; if not, create one (draft only — do NOT send it). "
        "3) Draft the onboarding welcome email using draft_onboarding_email (draft only — do NOT send it). "
        "4) Send a Teams channel notification using send_new_hire_card "
        f"to channel '{channel}' summarising what was done: the DocuSign draft "
        "and onboarding email draft are ready for HR to review. Include the employee name, email, "
        "start date, department, location, manager email, and a concise summary in the card."
    )


def build_new_hire_messages(payload: dict[str, Any]) -> list[BaseMessage]:
    """Construct the messages for a new-hire webhook payload."""
    return [HumanMessage(content=_new_hire_prompt(payload))]


def _docusign_prompt(envelope_id: str, status: str, employee_email: str) -> str:
    channel = _notification_channel()
    return (
        f"DocuSign envelope {envelope_id} for {employee_email} has changed to status: {status}. "
        f"1) If the status is 'completed', call update_tracker_stage with "
        f'stage="Offer Letter Signed" for {employee_email}. '
        f"2) If the status is 'sent', call update_tracker_stage with "
        f'stage="Sent Offer Letter" for {employee_email}. '
        "3) Send a Teams channel notification using send_docusign_status_card "
        f"to channel '{channel}' summarising the DocuSign status change."
    )


def build_docusign_messages(payload: dict[str, Any]) -> list[BaseMessage]:
    """Construct the messages for a DocuSign status webhook payload."""
    envelope_id = str(payload.get("envelope_id", ""))
    envelope_status = str(payload.get("status", ""))
    employee_email = str(payload.get("employee_email", ""))
    return [HumanMessage(content=_docusign_prompt(envelope_id, envelope_status, employee_email))]


def _background_clearance_prompt(employee_email: str, employee_name: str) -> str:
    channel = _notification_channel()
    return (
        f"Background clearance form submitted by {employee_name} ({employee_email}). "
        "Please run the following steps: "
        f"1) Call update_tracker_stage with stage='Background Submission' for {employee_email}. "
        "2) Send a Teams channel notification using send_background_clearance_card "
        f"to channel '{channel}' informing HR that {employee_name} "
        "has submitted their background clearance form. "
        f"3) Call send_background_clearance_confirmation for {employee_email} ({employee_name}) "
        "to send a confirmation email to the employee."
    )


def build_background_clearance_messages(payload: dict[str, Any]) -> list[BaseMessage]:
    """Construct the messages for a background-clearance webhook payload."""
    employee_email = str(payload.get("employeeEmail", ""))
    employee_name = str(payload.get("employeeName", ""))
    return [HumanMessage(content=_background_clearance_prompt(employee_email, employee_name))]


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
    """Run the agent for a queued new-hire payload."""
    messages = build_new_hire_messages(payload)
    employee_email = str(payload.get("employeeEmail", "")) or "unknown"
    await _run_agent_job("new-hire", employee_email, messages)

async def process_docusign_job(payload: dict[str, Any]) -> None:
    """Run the agent for a queued DocuSign status payload."""
    messages = build_docusign_messages(payload)
    envelope_id = str(payload.get("envelope_id", "")) or "unknown"
    await _run_agent_job("DocuSign", envelope_id, messages)


async def _run_agent_job(job_name: str, identifier: str, messages: list[BaseMessage]) -> None:
    started = time.perf_counter()
    try:
        await run_agent(messages, trigger_source="pa_webhook")
        logger.info(
            "Processed queued %s job for %s in %.3fs",
            job_name,
            identifier,
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Queued %s job failed for %s", job_name, identifier)
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
