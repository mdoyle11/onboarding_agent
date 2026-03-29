"""Onboarding email tools — draft and send with HR approval gate."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from string import Template
from typing import Any, cast

from fastmcp import FastMCP

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

# Persistent draft store — keyed by normalised (lowercased) employee_email.
# Stored as a JSON file so drafts survive server restarts.
_DRAFTS_PATH = Path(__file__).resolve().parents[3] / "data" / "email_drafts.json"


def _load_drafts() -> dict[str, dict[str, str]]:
    if _DRAFTS_PATH.exists():
        try:
            loaded = json.loads(_DRAFTS_PATH.read_text())
            return cast(dict[str, dict[str, str]], loaded)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read drafts file, starting fresh")
    return {}


def _save_drafts(drafts: dict[str, dict[str, str]]) -> None:
    _DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DRAFTS_PATH.write_text(json.dumps(drafts, indent=2))


def _email_client() -> Any:
    """Return the Outlook email client."""
    from onboarding_agent.integrations.outlook_email_client import OutlookEmailClient
    return OutlookEmailClient()


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


def register(mcp: FastMCP) -> None:
    """Register email draft and send tools on the given FastMCP instance."""

    @mcp.tool()
    async def draft_onboarding_email(
        employee_email: str,
        employee_name: str,
    ) -> dict[str, Any]:
        """
        Draft an onboarding welcome email for a new hire.
        Does NOT send the email — stores it for HR review.
        HR must explicitly approve by saying "send the onboarding email for [employee]".

        Parameters:
        - employee_email: The new hire's email address (recipient)
        - employee_name: Full name of the new hire

        Returns the rendered subject and a body preview for HR to review.
        """
        key = employee_email.strip().lower()
        try:
            subject, body_html = _render_template(employee_name)
        except FileNotFoundError:
            logger.error("Email template not found at %s", settings.email_template_path)
            return {
                "success": False,
                "error": f"Email template not found at {settings.email_template_path}",
            }

        drafts = _load_drafts()
        drafts[key] = {
            "to_email": employee_email.strip(),
            "subject": subject,
            "body_html": body_html,
        }
        _save_drafts(drafts)

        # Truncate preview for readability
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

    @mcp.tool()
    async def send_onboarding_email(employee_email: str) -> dict[str, Any]:
        """
        Send a previously drafted onboarding email.
        Must be explicitly requested by HR — e.g. "send the onboarding email for [employee]".

        Parameters:
        - employee_email: The new hire's email address (must have an existing draft)

        Fails if no draft exists. Call draft_onboarding_email first if needed.
        """
        key = employee_email.strip().lower()
        drafts = _load_drafts()
        logger.info("send_onboarding_email called for %s (key=%s), drafts=%s", employee_email, key, list(drafts.keys()))

        draft = drafts.get(key)
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
            from onboarding_agent.integrations.card_state import (
                mark_new_hire_action_complete,
                refresh_new_hire_card,
            )

            del drafts[key]
            _save_drafts(drafts)
            card = await mark_new_hire_action_complete(employee_email, "send_onboarding_email")
            if card is not None:
                await refresh_new_hire_card(employee_email)
            logger.info("Onboarding email sent to %s", employee_email)
            return {
                "success": True,
                "employee_email": employee_email,
                "message_id": result.get("message_id", ""),
                "message": f"Onboarding email sent to {employee_email}.",
            }

        # Preserve draft on failure so HR can retry
        logger.warning("Email send failed for %s: %s", employee_email, result.get("error"))
        return {
            "success": False,
            "employee_email": employee_email,
            "error": result.get("error", "Unknown error"),
            "message": f"Failed to send email to {employee_email}. Draft preserved — you can retry.",
        }

    @mcp.tool()
    async def send_background_clearance_confirmation(
        employee_email: str,
        employee_name: str,
    ) -> dict[str, Any]:
        """
        Send a confirmation email after an employee submits their background clearance form.
        This is sent immediately — no HR approval required.

        Parameters:
        - employee_email: The employee's email address
        - employee_name: Full name of the employee
        """
        return await send_background_clearance_confirmation_email(employee_email, employee_name)
