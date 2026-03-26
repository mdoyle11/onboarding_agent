"""DocuSign client — JWT Grant auth + envelope CRUD."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import jwt as pyjwt
from docusign_esign import (
    ApiClient,
    EnvelopeDefinition,
    EnvelopeEvent,
    EnvelopesApi,
    EventNotification,
    FoldersApi,
    RecipientEvent,
    Tabs,
    TemplateRole,
    Text,
)
from docusign_esign.client.api_exception import ApiException

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_BUFFER = 120  # seconds — refresh token this many seconds before expiry
_JWT_AUDIENCE = "account-d.docusign.com"  # demo; use "account.docusign.com" for production
_TOKEN_URL = "https://account-d.docusign.com/oauth/token"  # demo


class _TokenCache:
    """Simple in-process access token cache."""

    access_token: str = ""
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - _TOKEN_EXPIRY_BUFFER


_cache = _TokenCache()


class DocuSignClient:
    """Async-friendly DocuSign client using JWT Grant (server-to-server)."""

    def _get_access_token(self) -> str:
        """Return a valid access token, refreshing via JWT Grant if necessary."""
        if _cache.is_valid():
            return _cache.access_token

        private_key = Path(settings.docusign_private_key_path).read_bytes()

        now = int(time.time())
        payload = {
            "iss": settings.docusign_integration_key,
            "sub": settings.docusign_user_id,
            "aud": _JWT_AUDIENCE,
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        }

        encoded_jwt = pyjwt.encode(payload, private_key, algorithm="RS256")

        import urllib.parse
        import urllib.request

        data = urllib.parse.urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": encoded_jwt}
        ).encode()

        req = urllib.request.Request(
            _TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            import json
            token_data = json.loads(resp.read())

        _cache.access_token = token_data["access_token"]
        _cache.expires_at = time.time() + token_data.get("expires_in", 3600)
        return _cache.access_token

    def _get_api_client(self) -> ApiClient:
        api_client = ApiClient()
        api_client.host = settings.docusign_base_url
        api_client.set_default_header("Authorization", f"Bearer {self._get_access_token()}")
        return api_client

    # ------------------------------------------------------------------
    # Public async methods (sync DocuSign SDK wrapped in executor)
    # ------------------------------------------------------------------

    async def check_draft_exists(self, employee_email: str) -> dict[str, Any]:
        """Check whether a draft envelope exists for the given email."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._check_draft_exists_sync, employee_email
        )

    def _check_draft_exists_sync(self, employee_email: str) -> dict[str, Any]:
        try:
            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)
            folders_api = FoldersApi(api_client)
            result = folders_api.search(
                account_id=settings.docusign_account_id,
                search_folder_id="drafts",
                include_recipients="true",
                order="desc",
                order_by="created",
                count="25",
            )
            items = result.folder_items or []
            for item in items:
                envelope_id = item.envelope_id or ""
                actual_status = (item.status or "").lower()
                if not envelope_id or actual_status != "created":
                    continue

                try:
                    recipients_result = envelopes_api.list_recipients(
                        account_id=settings.docusign_account_id,
                        envelope_id=envelope_id,
                    )
                    recipient_emails = {
                        (signer.email or "").lower()
                        for signer in (recipients_result.signers or [])
                        if signer.email
                    }
                    if employee_email.lower() not in recipient_emails:
                        logger.info(
                            "Ignoring draft %s for %s because recipients=%s",
                            envelope_id,
                            employee_email,
                            sorted(recipient_emails),
                        )
                        continue
                except ApiException:
                    logger.info("Ignoring stale draft reference %s", envelope_id)
                    continue

                return {
                    "exists": True,
                    "envelope_id": envelope_id,
                    "status": actual_status,
                }
            return {"exists": False, "envelope_id": ""}
        except ApiException as exc:
            logger.exception("check_draft_exists failed")
            return {"exists": False, "envelope_id": "", "error": str(exc)}

    async def create_envelope_draft(
        self,
        employee_name: str,
        employee_email: str,
        start_date: str,
        department: str,
    ) -> dict[str, Any]:
        """Create a DocuSign envelope draft using the configured template."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._create_envelope_draft_sync,
            employee_name,
            employee_email,
            start_date,
            department,
        )

    def _create_envelope_draft_sync(
        self,
        employee_name: str,
        employee_email: str,
        start_date: str,
        department: str,
    ) -> dict[str, Any]:
        try:
            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)

            signer_role = TemplateRole(
                email=employee_email,
                name=employee_name,
                role_name="signer",
                tabs=Tabs(
                    text_tabs=[
                        Text(tab_label="StartDate", value=start_date),
                        Text(tab_label="Department", value=department),
                    ]
                ),
            )

            # Build event notification if a Connect URL is configured
            event_notification = None
            if settings.docusign_connect_url:
                event_notification = EventNotification(
                    url=f"{settings.docusign_connect_url}/webhook/docusign",
                    logging_enabled="true",
                    require_acknowledgment="true",
                    use_soap_interface="false",
                    include_envelope_void_reason="true",
                    include_document_fields="true",
                    envelope_events=[
                        EnvelopeEvent(envelope_event_status_code="sent"),
                        EnvelopeEvent(envelope_event_status_code="delivered"),
                        EnvelopeEvent(envelope_event_status_code="completed"),
                        EnvelopeEvent(envelope_event_status_code="voided"),
                    ],
                    recipient_events=[
                        RecipientEvent(recipient_event_status_code="Completed"),
                    ],
                )

            envelope_def = EnvelopeDefinition(
                template_id=settings.docusign_template_id,
                template_roles=[signer_role],
                status="created",  # draft — not yet sent
                event_notification=event_notification,
                custom_fields={
                    "textCustomFields": [
                        {"name": "employee_email", "value": employee_email, "show": "false"}
                    ]
                },
            )

            result = envelopes_api.create_envelope(
                account_id=settings.docusign_account_id,
                envelope_definition=envelope_def,
            )
            return {
                "success": True,
                "envelope_id": result.envelope_id or "",
                "status": result.status or "created",
            }
        except ApiException as exc:
            logger.exception("create_envelope_draft failed")
            return {"success": False, "envelope_id": "", "status": "", "error": str(exc)}

    async def send_envelope(self, envelope_id: str) -> dict[str, Any]:
        """Transition an envelope from draft to sent."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._send_envelope_sync, envelope_id
        )

    def _send_envelope_sync(self, envelope_id: str) -> dict[str, Any]:
        try:
            from docusign_esign import Envelope

            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)

            envelope = Envelope(status="sent")
            envelopes_api.update(
                account_id=settings.docusign_account_id,
                envelope_id=envelope_id,
                envelope=envelope,
            )
            return {"success": True, "envelope_id": envelope_id, "status": "sent"}
        except ApiException as exc:
            logger.exception("send_envelope failed")
            return {"success": False, "envelope_id": envelope_id, "status": "", "error": str(exc)}

    async def get_envelope_status(self, envelope_id: str) -> dict[str, Any]:
        """Get envelope status and recipient tracking."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._get_envelope_status_sync, envelope_id
        )

    def _get_envelope_status_sync(self, envelope_id: str) -> dict[str, Any]:
        try:
            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)

            envelope = envelopes_api.get_envelope(
                account_id=settings.docusign_account_id,
                envelope_id=envelope_id,
            )
            recipients_result = envelopes_api.list_recipients(
                account_id=settings.docusign_account_id,
                envelope_id=envelope_id,
            )

            recipients = []
            for signer in (recipients_result.signers or []):
                recipients.append(
                    {
                        "name": signer.name,
                        "email": signer.email,
                        "status": signer.status,
                        "signed_date_time": signer.signed_date_time,
                    }
                )

            return {
                "envelope_id": envelope_id,
                "status": envelope.status or "",
                "recipients": recipients,
            }
        except ApiException as exc:
            logger.exception("get_envelope_status failed")
            return {"envelope_id": envelope_id, "status": "", "recipients": [], "error": str(exc)}
