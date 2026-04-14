"""Onboarding email tools — draft and send with HR approval gate."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from string import Template
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.config import settings
from onboarding_agent.mcp_server.clients import email_client as _email_client
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import TTL_SECONDS_FIELD

logger = logging.getLogger(__name__)

NS_EMAIL_DRAFTS = "email_drafts"
_EMAIL_DRAFT_TTL_SECONDS = 30 * 24 * 60 * 60


def _parse_email_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    raw_parts = value.replace(";", ",").split(",") if isinstance(value, str) else list(value)

    emails: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        email = str(raw).strip()
        if not email or "@" not in email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(email)
    return emails


def _clear_to_start_cc_emails(extra_cc_emails: str | list[str] | tuple[str, ...] | None = None) -> list[str]:
    configured_emails = _parse_email_list(settings.clear_to_start_cc_emails)
    configured_keys = {email.lower() for email in configured_emails}
    extra_emails = [
        email
        for email in _parse_email_list(extra_cc_emails)
        if email.lower() not in configured_keys
    ]
    return configured_emails + extra_emails


def _store() -> Any:
    assert store_mod.store is not None, "State store not initialized"
    return store_mod.store


def _resolve_template_path(template_path: str | Path) -> Path:
    """Resolve a template path in local dev and installed container layouts."""
    resolved = Path(template_path)
    if resolved.is_absolute():
        return resolved

    cwd_candidate = Path.cwd() / resolved
    if cwd_candidate.exists():
        return cwd_candidate

    return Path(__file__).resolve().parents[2] / resolved


def _resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved

    cwd_candidate = Path.cwd() / resolved
    if cwd_candidate.exists():
        return cwd_candidate

    return Path(__file__).resolve().parents[2] / resolved


def _file_attachment(path: str | Path) -> dict[str, str]:
    resolved = _resolve_project_path(path)
    content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": resolved.name,
        "contentType": content_type,
        "contentBytes": base64.b64encode(resolved.read_bytes()).decode("ascii"),
    }


def _i9_documents_attachment() -> dict[str, str]:
    return _file_attachment(settings.i9_documents_attachment_path)


def _render_template(employee_name: str) -> tuple[str, str]:
    """Load and render the onboarding email template. Returns (subject, body_html)."""
    template_path = _resolve_template_path(settings.email_template_path)

    template_vars = {"employee_name": employee_name}

    body_html = Template(template_path.read_text()).safe_substitute(template_vars)
    subject = Template(settings.email_subject_template).safe_substitute(template_vars)

    return subject, body_html


async def send_background_clearance_confirmation_email(
    employee_email: str,
    employee_name: str,
) -> dict[str, Any]:
    """Send the background-clearance confirmation email directly."""
    template_path = _resolve_template_path("templates/background_clearance_confirmation.html")
    try:
        body_html = Template(template_path.read_text()).safe_substitute(
            employee_name=employee_name,
        )
    except FileNotFoundError:
        logger.error("Background clearance template not found at %s", template_path)
        return {
            "success": False,
            "error": f"Template not found: {template_path}",
        }

    subject = f"Background Clearance Form Received — {employee_name}"

    result = await _email_client().send_email(
        to_email=employee_email.strip(),
        subject=subject,
        body_html=body_html,
    )

    if result.get("success"):
        logger.info("Background clearance confirmation sent to %s", employee_email)
        return {
            "success": True,
            "employee_email": employee_email,
            "message": f"Background clearance confirmation email sent to {employee_email}.",
        }

    logger.warning("Background clearance email failed for %s: %s", employee_email, result.get("error"))
    return {
        "success": False,
        "employee_email": employee_email,
        "error": result.get("error", "Unknown error"),
    }


async def send_clear_to_start_email(
    employee_email: str,
    employee_name: str,
    *,
    requested_start_date: str = "",
    treasurer_name: str = "",
    treasurer_email: str = "",
    hiring_manager_name: str = "",
    hiring_manager_email: str = "",
    cc_emails: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Send the Clear to Start email directly, with configured and requested CC recipients."""
    template_path = _resolve_template_path("templates/clear_to_start_email.html")
    try:
        body_html = Template(template_path.read_text()).safe_substitute(
            employee_name=employee_name,
            requested_start_date=requested_start_date,
            treasurer_name=treasurer_name,
            hiring_manager_name=hiring_manager_name,
        )
    except FileNotFoundError:
        logger.error("Clear to Start template not found at %s", template_path)
        return {
            "success": False,
            "employee_email": employee_email,
            "error": f"Template not found: {template_path}",
        }

    subject = f"Clear to Start — {employee_name}"
    direct_cc_emails = _parse_email_list([treasurer_email, hiring_manager_email])
    all_extra_cc_emails = _parse_email_list(cc_emails) + direct_cc_emails
    cc_list = [
        email
        for email in _clear_to_start_cc_emails(all_extra_cc_emails)
        if email.lower() != employee_email.strip().lower()
    ]
    try:
        attachments = [_i9_documents_attachment()]
    except OSError as exc:
        logger.error("I-9 documents attachment could not be loaded: %s", exc)
        return {
            "success": False,
            "employee_email": employee_email,
            "cc_emails": cc_list,
            "treasurer_name": treasurer_name,
            "treasurer_email": treasurer_email,
            "hiring_manager_name": hiring_manager_name,
            "hiring_manager_email": hiring_manager_email,
            "error": f"I-9 documents attachment could not be loaded: {exc}",
        }

    result = await _email_client().send_email(
        to_email=employee_email.strip(),
        subject=subject,
        body_html=body_html,
        cc_emails=cc_list,
        attachments=attachments,
    )

    if result.get("success"):
        logger.info("Clear to Start email sent to %s cc=%s", employee_email, cc_list)
        return {
            "success": True,
            "employee_email": employee_email,
            "cc_emails": cc_list,
            "treasurer_name": treasurer_name,
            "treasurer_email": treasurer_email,
            "hiring_manager_name": hiring_manager_name,
            "hiring_manager_email": hiring_manager_email,
            "message": f"Clear to Start email sent to {employee_email}.",
        }

    logger.warning("Clear to Start email failed for %s: %s", employee_email, result.get("error"))
    return {
        "success": False,
        "employee_email": employee_email,
        "cc_emails": cc_list,
        "treasurer_name": treasurer_name,
        "treasurer_email": treasurer_email,
        "hiring_manager_name": hiring_manager_name,
        "hiring_manager_email": hiring_manager_email,
        "error": result.get("error", "Unknown error"),
    }


async def draft_onboarding_email_for_employee(
    employee_email: str,
    employee_name: str,
) -> dict[str, Any]:
    """Create and persist an onboarding email draft for an employee."""
    key = employee_email.strip().lower()
    try:
        subject, body_html = _render_template(employee_name)
    except FileNotFoundError:
        logger.error("Email template not found at %s", settings.email_template_path)
        return {
            "success": False,
            "error": f"Email template not found at {settings.email_template_path}",
        }

    await _store().put(NS_EMAIL_DRAFTS, key, {
        "to_email": employee_email.strip(),
        "subject": subject,
        "body_html": body_html,
        TTL_SECONDS_FIELD: _EMAIL_DRAFT_TTL_SECONDS,
    })

    preview = body_html[:500] + ("…" if len(body_html) > 500 else "")
    logger.info("Email draft created and persisted for %s", employee_email)
    return {
        "success": True,
        "employee_email": employee_email,
        "subject": subject,
        "body_preview": preview,
        "message": (
            f"Onboarding email drafted for {employee_name} ({employee_email}). "
            "Awaiting HR approval to send."
        ),
    }


async def send_onboarding_email_to_employee(employee_email: str) -> dict[str, Any]:
    """Send a previously drafted onboarding email for an employee."""
    key = employee_email.strip().lower()
    draft = await _store().get(NS_EMAIL_DRAFTS, key)
    if not draft:
        return {
            "success": False,
            "error": (
                f"No email draft found for {employee_email}. "
                "Call draft_onboarding_email first to create a draft."
            ),
        }

    try:
        attachments = [_i9_documents_attachment()]
    except OSError as exc:
        logger.error("I-9 documents attachment could not be loaded: %s", exc)
        return {
            "success": False,
            "employee_email": employee_email,
            "error": f"I-9 documents attachment could not be loaded: {exc}",
            "message": f"Failed to send email to {employee_email}. Draft preserved — you can retry.",
        }

    result = await _email_client().send_email(
        to_email=draft["to_email"],
        subject=draft["subject"],
        body_html=draft["body_html"],
        attachments=attachments,
    )

    if result.get("success"):
        await _store().delete(NS_EMAIL_DRAFTS, key)
        logger.info("Onboarding email sent to %s", employee_email)
        return {
            "success": True,
            "employee_email": employee_email,
            "message_id": result.get("message_id", ""),
            "message": f"Onboarding email sent to {employee_email}.",
        }

    logger.warning("Email send failed for %s: %s", employee_email, result.get("error"))
    return {
        "success": False,
        "employee_email": employee_email,
        "error": result.get("error", "Unknown error"),
        "message": f"Failed to send email to {employee_email}. Draft preserved — you can retry.",
    }


def register(mcp: FastMCP) -> None:
    """Register email draft and send tools on the given FastMCP instance."""

    @mcp.tool()
    async def draft_onboarding_email(
        employee_email: str,
        employee_name: str,
    ) -> dict[str, Any]:
        """Create and persist a welcome-email draft for HR review.

        This does not send the email. Use it before `send_onboarding_email`
        when no draft exists yet.
        """
        return await draft_onboarding_email_for_employee(employee_email, employee_name)

    @mcp.tool()
    async def send_onboarding_email(employee_email: str) -> dict[str, Any]:
        """Send a previously drafted onboarding email for one employee.

        This requires an existing draft. If no draft exists, call
        `draft_onboarding_email` first.
        """
        return await send_onboarding_email_to_employee(employee_email)

    @mcp.tool()
    async def send_background_clearance_confirmation(
        employee_email: str,
        employee_name: str,
    ) -> dict[str, Any]:
        """Send the background-clearance confirmation email immediately."""
        return await send_background_clearance_confirmation_email(employee_email, employee_name)

    @mcp.tool()
    async def send_clear_to_start(
        employee_email: str,
        employee_name: str,
        requested_start_date: str = "",
        treasurer_name: str = "",
        treasurer_email: str = "",
        hiring_manager_name: str = "",
        hiring_manager_email: str = "",
        cc_emails: str = "",
    ) -> dict[str, Any]:
        """Send the Clear to Start email immediately.

        Provide `treasurer_name`, `treasurer_email`, and
        `hiring_manager_email`; use `hiring_manager_name` when it cannot be
        resolved from the tracker. Treasurer and Hiring Manager emails are CC'd
        automatically. Use `cc_emails` for comma-separated extra CC recipients.
        Configured Clear to Start CC recipients are included automatically.
        """
        return await send_clear_to_start_email(
            employee_email,
            employee_name,
            requested_start_date=requested_start_date,
            treasurer_name=treasurer_name,
            treasurer_email=treasurer_email,
            hiring_manager_name=hiring_manager_name,
            hiring_manager_email=hiring_manager_email,
            cc_emails=cc_emails,
        )
