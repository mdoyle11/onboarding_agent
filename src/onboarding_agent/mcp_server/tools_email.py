"""Onboarding email tools — draft and send with HR approval gate."""

from __future__ import annotations

import logging
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

    result = await _email_client().send_email(
        to_email=draft["to_email"],
        subject=draft["subject"],
        body_html=draft["body_html"],
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
