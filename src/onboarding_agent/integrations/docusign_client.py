"""DocuSign client — JWT Grant auth + envelope CRUD."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
from typing import Any

import jwt as pyjwt
from docusign_esign import (
    ApiClient,
    EnvelopeDefinition,
    EnvelopeEvent,
    EnvelopesApi,
    EventNotification,
    FoldersApi,
    FoldersRequest,
    RecipientEvent,
    Tabs,
    TemplateRole,
    Text,
)
from docusign_esign.client.api_exception import ApiException

from onboarding_agent.config import settings
from onboarding_agent.domain.formatting import format_date

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

        private_key = settings.docusign_private_key_bytes()

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

    async def check_draft_exists(
        self,
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        """Check whether a draft envelope exists for the given email."""
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None, self._check_draft_exists_sync, employee_email, work_location, job_title, status_change
        )
        logger.info(
            "DocuSign check_draft_exists completed for %s in %.3fs exists=%s",
            employee_email,
            time.perf_counter() - started,
            result.get("exists", False),
        )
        return result

    async def find_latest_envelope_for_employee(
        self,
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        """Find the most recent envelope for an employee across active/completed states."""
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self._find_latest_envelope_for_employee_sync,
            employee_email,
            work_location,
            job_title,
            status_change,
        )
        logger.info(
            "DocuSign find_latest_envelope_for_employee completed for %s in %.3fs found=%s",
            employee_email,
            time.perf_counter() - started,
            result.get("found", False),
        )
        return result

    async def list_draft_envelopes(
        self,
        employee_email: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        """List draft envelopes waiting to be sent, optionally filtered."""
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self._list_draft_envelopes_sync,
            employee_email,
            work_location,
            job_title,
            status_change,
            limit,
        )
        logger.info(
            "DocuSign list_draft_envelopes completed in %.3fs returned=%s total=%s",
            time.perf_counter() - started,
            len(result.get("drafts", [])),
            result.get("total_count", 0),
        )
        return result

    @staticmethod
    def _custom_field_map(envelope: Any) -> dict[str, str]:
        fields = getattr(envelope, "custom_fields", None)
        if fields is None:
            return {}
        if isinstance(fields, dict):
            text_fields = fields.get("textCustomFields") or fields.get("text_custom_fields") or []
        else:
            text_fields = (
                getattr(fields, "text_custom_fields", None)
                or getattr(fields, "textCustomFields", None)
                or []
            )

        result: dict[str, str] = {}
        for field in text_fields:
            if isinstance(field, dict):
                name = str(field.get("name", "") or "")
                value = str(field.get("value", "") or "")
            else:
                name = str(getattr(field, "name", "") or "")
                value = str(getattr(field, "value", "") or "")
            if name:
                result[name] = value
        return result

    def _matches_identity_fields(
        self,
        field_map: dict[str, str],
        *,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> bool:
        if work_location and field_map.get("work_location", "").strip().lower() != work_location.strip().lower():
            return False
        if job_title and field_map.get("job_title", "").strip().lower() != job_title.strip().lower():
            return False
        return not (
            status_change
            and field_map.get("status_change", "").strip().lower() != status_change.strip().lower()
        )

    def _folder_id(self, folders_api: FoldersApi, *, kind: str) -> str:
        folders = folders_api.list(account_id=settings.docusign_account_id)
        for folder in (folders.folders or []):
            folder_type = str(getattr(folder, "type", "") or "").strip().lower()
            folder_name = str(getattr(folder, "name", "") or "").strip().lower()
            if kind == "deleted":
                if folder_type in {"recyclebin", "recycle_bin", "deleteditems", "deleted_items"}:
                    return str(getattr(folder, "folder_id", "") or "")
                if folder_name in {"deleted", "deleted items", "recycle bin", "trash"}:
                    return str(getattr(folder, "folder_id", "") or "")
            if kind == "drafts":
                if folder_type in {"draft", "drafts"}:
                    return str(getattr(folder, "folder_id", "") or "")
                if folder_name in {"draft", "drafts"}:
                    return str(getattr(folder, "folder_id", "") or "")
        return ""

    def _envelope_identity(self, envelopes_api: EnvelopesApi, envelope_id: str) -> dict[str, str]:
        envelope = envelopes_api.get_envelope(
            account_id=settings.docusign_account_id,
            envelope_id=envelope_id,
            include="custom_fields",
        )
        field_map = self._custom_field_map(envelope)
        recipients_result = envelopes_api.list_recipients(
            account_id=settings.docusign_account_id,
            envelope_id=envelope_id,
        )
        first_signer = (recipients_result.signers or [None])[0]
        signer_email = str(getattr(first_signer, "email", "") or "")
        signer_name = str(getattr(first_signer, "name", "") or "")
        return {
            "employee_email": field_map.get("employee_email", "") or signer_email,
            "employee_name": signer_name,
            "work_location": field_map.get("work_location", ""),
            "job_title": field_map.get("job_title", ""),
            "status_change": field_map.get("status_change", ""),
            "submission_id": field_map.get("submission_id", ""),
            "status": str(getattr(envelope, "status", "") or ""),
        }

    def _search_envelopes_sync(
        self,
        employee_email: str,
        *,
        folder_id: str,
        count: str,
        require_status: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> tuple[str, str] | None:
        """Search a DocuSign folder for the first envelope matching *employee_email*.

        Returns ``(envelope_id, status)`` on match, or ``None``.
        """
        api_client = self._get_api_client()
        envelopes_api = EnvelopesApi(api_client)
        folders_api = FoldersApi(api_client)
        result = folders_api.search(
            account_id=settings.docusign_account_id,
            search_folder_id=folder_id,
            include_recipients="true",
            order="desc",
            order_by="created",
            count=count,
        )
        normalized_email = employee_email.lower()

        for item in (result.folder_items or []):
            envelope_id = item.envelope_id or ""
            actual_status = (item.status or "").lower()
            if not envelope_id:
                continue
            if require_status and actual_status != require_status:
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
                if normalized_email not in recipient_emails:
                    continue
                if work_location or job_title or status_change:
                    envelope = envelopes_api.get_envelope(
                        account_id=settings.docusign_account_id,
                        envelope_id=envelope_id,
                        include="custom_fields",
                    )
                    if not self._matches_identity_fields(
                        self._custom_field_map(envelope),
                        work_location=work_location,
                        job_title=job_title,
                        status_change=status_change,
                    ):
                        continue
            except ApiException:
                logger.info("Ignoring stale envelope reference %s", envelope_id)
                continue

            return envelope_id, actual_status
        return None

    def _search_envelopes_bulk_sync(
        self,
        *,
        folder_id: str,
        count: str,
        employee_email: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> list[dict[str, str]]:
        """Search a DocuSign logical folder and return all matching envelopes."""
        api_client = self._get_api_client()
        envelopes_api = EnvelopesApi(api_client)
        folders_api = FoldersApi(api_client)
        result = folders_api.search(
            account_id=settings.docusign_account_id,
            search_folder_id=folder_id,
            include_recipients="true",
            order="desc",
            order_by="created",
            count=count,
        )
        normalized_email = employee_email.strip().lower()
        matches: list[dict[str, str]] = []

        for item in (getattr(result, "folder_items", None) or []):
            envelope_id = str(getattr(item, "envelope_id", "") or "")
            actual_status = str(getattr(item, "status", "") or "").lower()
            if not envelope_id:
                continue
            try:
                identity = self._envelope_identity(envelopes_api, envelope_id)
            except ApiException:
                logger.info("Ignoring stale envelope reference %s", envelope_id)
                continue
            if normalized_email and identity.get("employee_email", "").strip().lower() != normalized_email:
                continue
            if not self._matches_identity_fields(
                {
                    "work_location": identity.get("work_location", ""),
                    "job_title": identity.get("job_title", ""),
                    "status_change": identity.get("status_change", ""),
                },
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            ):
                continue
            matches.append(
                {
                    "envelope_id": envelope_id,
                    "employee_email": identity.get("employee_email", ""),
                    "employee_name": identity.get("employee_name", ""),
                    "work_location": identity.get("work_location", ""),
                    "job_title": identity.get("job_title", ""),
                    "status_change": identity.get("status_change", ""),
                    "submission_id": identity.get("submission_id", ""),
                    "status": actual_status or identity.get("status", ""),
                    "created_date_time": str(getattr(item, "created_date_time", "") or ""),
                }
            )
        return matches

    def _check_draft_exists_sync(
        self,
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        try:
            match = self._search_envelopes_sync(
                employee_email,
                folder_id="drafts",
                count="25",
                require_status="created",
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
            if match:
                return {"exists": True, "envelope_id": match[0], "status": match[1]}
            return {"exists": False, "envelope_id": ""}
        except ApiException as exc:
            logger.exception("check_draft_exists failed")
            return {"exists": False, "envelope_id": "", "error": str(exc)}

    def _list_draft_envelopes_sync(
        self,
        employee_email: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        try:
            matches = self._search_envelopes_bulk_sync(
                folder_id="drafts",
                count="100",
                employee_email=employee_email,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
            return {
                "drafts": matches[: max(limit, 0)],
                "total_count": len(matches),
            }
        except ApiException as exc:
            logger.exception("list_draft_envelopes failed")
            return {"drafts": [], "total_count": 0, "error": str(exc)}

    def _find_latest_envelope_for_employee_sync(
        self,
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        try:
            match = self._search_envelopes_sync(
                employee_email,
                folder_id="all",
                count="50",
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
            if match:
                return {"found": True, "envelope_id": match[0], "status": match[1]}
            return {"found": False, "envelope_id": "", "status": ""}
        except ApiException as exc:
            logger.exception("find_latest_envelope_for_employee failed")
            return {"found": False, "envelope_id": "", "status": "", "error": str(exc)}

    async def create_envelope_draft(
        self,
        employee_name: str,
        employee_email: str,
        start_date: str,
        position: str,
        work_location: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Create a DocuSign envelope draft using the configured template."""
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self._create_envelope_draft_sync,
            employee_name,
            employee_email,
            start_date,
            position,
            work_location,
            status_change,
            submission_id,
        )
        logger.info(
            "DocuSign create_envelope_draft completed for %s in %.3fs success=%s",
            employee_email,
            time.perf_counter() - started,
            result.get("success", False),
        )
        return result

    def _create_envelope_draft_sync(
        self,
        employee_name: str,
        employee_email: str,
        start_date: str,
        position: str,
        work_location: str,
        status_change: str,
        submission_id: str,
    ) -> dict[str, Any]:
        try:
            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)
            formatted_start_date = format_date(start_date) or start_date

            signer_role = TemplateRole(
                email=employee_email,
                name=employee_name,
                role_name="signer",
                tabs=Tabs(
                    text_tabs=[
                        Text(tab_label="StartDate", value=formatted_start_date),
                        # Keep template tab label stable for existing DocuSign template wiring.
                        Text(tab_label="Department", value=position),
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
                        {"name": "employee_email", "value": employee_email, "show": "false"},
                        {"name": "job_title", "value": position, "show": "false"},
                        {"name": "work_location", "value": work_location, "show": "false"},
                        {"name": "status_change", "value": status_change, "show": "false"},
                        {"name": "submission_id", "value": submission_id, "show": "false"},
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
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None, self._send_envelope_sync, envelope_id
        )
        logger.info(
            "DocuSign send_envelope completed for %s in %.3fs success=%s",
            envelope_id[:8],
            time.perf_counter() - started,
            result.get("success", False),
        )
        return result

    async def delete_draft_envelope(self, envelope_id: str) -> dict[str, Any]:
        """Delete an unsent draft envelope by moving it to the deleted folder."""
        started = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(
            None, self._delete_draft_envelope_sync, envelope_id
        )
        logger.info(
            "DocuSign delete_draft_envelope completed for %s in %.3fs success=%s",
            envelope_id[:8] if envelope_id else "unknown",
            time.perf_counter() - started,
            result.get("success", False),
        )
        return result

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

    def _delete_draft_envelope_sync(self, envelope_id: str) -> dict[str, Any]:
        try:
            api_client = self._get_api_client()
            envelopes_api = EnvelopesApi(api_client)
            folders_api = FoldersApi(api_client)
            identity = self._envelope_identity(envelopes_api, envelope_id)
            status = str(identity.get("status", "") or "").strip().lower()
            if status != "created":
                return {
                    "success": False,
                    "envelope_id": envelope_id,
                    "status": status,
                    "error": "Only draft envelopes in created status can be deleted.",
                }

            deleted_folder_id = self._folder_id(folders_api, kind="deleted")
            if not deleted_folder_id:
                return {
                    "success": False,
                    "envelope_id": envelope_id,
                    "status": status,
                    "error": "DocuSign deleted folder not found.",
                }
            drafts_folder_id = self._folder_id(folders_api, kind="drafts")
            if not drafts_folder_id:
                return {
                    "success": False,
                    "envelope_id": envelope_id,
                    "status": status,
                    "error": "DocuSign drafts folder not found.",
                }

            folders_api.move_envelopes(
                account_id=settings.docusign_account_id,
                folder_id=deleted_folder_id,
                folders_request=FoldersRequest(
                    envelope_ids=[envelope_id],
                    from_folder_id=drafts_folder_id,
                ),
            )
            return {
                "success": True,
                "envelope_id": envelope_id,
                **identity,
                "status": "deleted",
            }
        except ApiException as exc:
            logger.exception("delete_draft_envelope failed")
            return {"success": False, "envelope_id": envelope_id, "status": "", "error": str(exc)}

    async def get_envelope_status(self, envelope_id: str) -> dict[str, Any]:
        """Get envelope status and recipient tracking."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._get_envelope_status_sync, envelope_id
        )

    async def create_envelope_edit_view(self, envelope_id: str) -> dict[str, Any]:
        """Create a sender edit/review URL for an existing envelope."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._create_envelope_edit_view_sync, envelope_id
        )

    def _create_envelope_edit_view_sync(self, envelope_id: str) -> dict[str, Any]:
        try:
            return_url = settings.docusign_base_url.rsplit("/restapi", 1)[0].rstrip("/") + "/"
            body = json.dumps({"returnUrl": return_url}).encode("utf-8")
            req = urllib.request.Request(
                f"{settings.docusign_base_url}/v2.1/accounts/{settings.docusign_account_id}/envelopes/{envelope_id}/views/edit",
                data=body,
                headers={
                    "Authorization": f"Bearer {self._get_access_token()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                payload = json.loads(resp.read())
            return {
                "success": True,
                "url": str(payload.get("url", "") or ""),
                "envelope_id": envelope_id,
            }
        except Exception as exc:
            logger.exception("create_envelope_edit_view failed")
            return {"success": False, "url": "", "envelope_id": envelope_id, "error": str(exc)}

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
