"""Outlook email client — sends via Microsoft Graph API Mail.Send permission.

Requires admin consent for the Mail.Send application permission on the Azure AD
app registration. Until consent is granted, all sends return an error.
"""

from __future__ import annotations

import logging
from typing import Any

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)


class OutlookEmailClient:
    """Send email as an Outlook/Exchange user via Microsoft Graph API."""

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        reply_to: str = "",
    ) -> dict[str, Any]:
        """Send an HTML email via Graph API. Returns {success, message_id}."""
        # TODO: Implement when Mail.Send admin consent is granted.
        # Will use msgraph SDK with existing Azure AD credentials:
        #   POST /users/{outlook_sender_email}/sendMail
        logger.warning(
            "Outlook email not yet active — awaiting admin consent for Mail.Send. "
            "Attempted send to %s with subject: %s",
            to_email,
            subject,
        )
        return {
            "success": False,
            "error": (
                "Outlook email backend is not yet active. "
                "An Azure AD admin must grant Mail.Send application permission. "
                "Switch to EMAIL_BACKEND=gmail for testing."
            ),
        }
