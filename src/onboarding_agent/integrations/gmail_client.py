"""Gmail email client — sends via Gmail API using OAuth2 refresh token."""

from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailClient:
    """Send email via Gmail API using OAuth2 client credentials + refresh token."""

    def _get_credentials(self) -> Credentials:
        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=_SCOPES,
        )
        creds.refresh(Request())
        return creds

    def _send_sync(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        reply_to: str,
    ) -> dict[str, Any]:
        creds = self._get_credentials()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = settings.gmail_sender_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(body_html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        message_id = result.get("id", "")
        logger.info("Gmail sent: to=%s message_id=%s", to_email, message_id)
        return {"success": True, "message_id": message_id}

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        reply_to: str = "",
    ) -> dict[str, Any]:
        """Send an HTML email via Gmail API. Returns {success, message_id}."""
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, to_email, subject, body_html, reply_to
            )
        except Exception as exc:
            logger.exception("Gmail send failed: %s", exc)
            return {"success": False, "error": str(exc)}
