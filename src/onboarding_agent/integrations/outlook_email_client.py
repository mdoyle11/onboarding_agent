"""Outlook email client — sends via Microsoft Graph API Mail.Send permission."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from onboarding_agent.config import settings
from onboarding_agent.integrations.graph.auth import graph_access_token

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
        if not settings.outlook_sender_email:
            return {"success": False, "error": "OUTLOOK_SENDER_EMAIL is not configured."}

        message_payload: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body_html,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email,
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }
        if reply_to:
            message_payload["message"]["replyTo"] = [
                {
                    "emailAddress": {
                        "address": reply_to,
                    }
                }
            ]

        try:
            token = await graph_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            url = (
                f"https://graph.microsoft.com/v1.0/users/"
                f"{settings.outlook_sender_email}/sendMail"
            )
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, json=message_payload, headers=headers) as resp,
            ):
                if resp.status == 202:
                    logger.info("Outlook email sent to %s with subject %s", to_email, subject)
                    return {"success": True, "message_id": ""}
                error_text = await resp.text()
                logger.warning(
                    "Outlook sendMail failed for %s via %s: HTTP %s %s",
                    to_email,
                    settings.outlook_sender_email,
                    resp.status,
                    error_text,
                )
                return {
                    "success": False,
                    "error": f"Graph sendMail failed ({resp.status}): {error_text}",
                }
        except Exception as exc:
            logger.exception("Outlook send_email failed for %s", to_email)
            return {"success": False, "error": str(exc)}
