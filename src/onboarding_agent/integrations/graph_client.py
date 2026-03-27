"""Microsoft Graph API client — Excel tracker, Teams, and Forms."""

from __future__ import annotations

import logging
from datetime import date
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote

import aiohttp
from azure.identity.aio import ClientSecretCredential
from msgraph import GraphServiceClient  # type: ignore[attr-defined]

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://graph.microsoft.com/.default"]

# ---------------------------------------------------------------------------
# Column layout (zero-based) — aligned with the Google Sheets tracker
# ---------------------------------------------------------------------------
# A     B      C         D          E           F              G                  H
# Name  Email  Location  StartDate  Department  ManagerEmail   AddedToTracker     SentOfferLetter
# I                    J                      K                   L          M               N              O
# OfferLetterSigned    BackgroundSubmission   BackgroundCleared   AddedToADP CompleteInADP   ClearToStart   ProrationsSent

_COL_NAME = 0
_COL_EMAIL = 1
_COL_LOCATION = 2
_COL_START_DATE = 3
_COL_DEPARTMENT = 4
_COL_MANAGER_EMAIL = 5

STAGES: dict[str, int] = {
    "Added to Tracker": 6,
    "Sent Offer Letter": 7,
    "Offer Letter Signed": 8,
    "Background Submission": 9,
    "Background Cleared": 10,
    "Added to ADP": 11,
    "Complete in ADP": 12,
    "Clear to Start": 13,
    "Prorations Sent": 14,
}

ALL_STAGES = list(STAGES.keys())
ACTIVE_STAGES = ["Added to Tracker", "Sent Offer Letter", "Offer Letter Signed"]

HEADER_ROW = [
    "Name",
    "Email",
    "Location",
    "StartDate",
    "Department",
    "ManagerEmail",
    "Added to Tracker",
    "Sent Offer Letter",
    "Offer Letter Signed",
    "Background Submission",
    "Background Cleared",
    "Added to ADP",
    "Complete in ADP",
    "Clear to Start",
    "Prorations Sent",
]


def _today() -> str:
    return date.today().isoformat()


def _row_to_stages(row: list[Any]) -> dict[str, str]:
    return {
        stage: str(row[col_idx]) if len(row) > col_idx and row[col_idx] is not None else ""
        for stage, col_idx in STAGES.items()
    }


def _latest_active_stage(stages: dict[str, str]) -> str:
    latest = ""
    for stage in ACTIVE_STAGES:
        if stages.get(stage):
            latest = stage
    return latest


class GraphClient:
    """Thin wrapper around the Microsoft Graph SDK for onboarding operations."""

    def _get_client(self) -> GraphServiceClient:
        credential = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        return GraphServiceClient(credential, scopes=_SCOPES)

    async def _used_range_rows(self) -> list[list[Any]]:
        data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(settings.graph_excel_sheet_name)}/usedRange(valuesOnly=true)",
        )
        values = data.get("values", []) if isinstance(data, dict) else []
        if not values:
            return []
        return cast(list[list[Any]], values)

    async def _graph_access_token(self) -> str:
        cred = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        try:
            token = await cred.get_token("https://graph.microsoft.com/.default")
            return token.token
        finally:
            await cred.close()

    async def _graph_workbook_request(
        self,
        method: str,
        workbook_path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        token = await self._graph_access_token()
        url = (
            "https://graph.microsoft.com/v1.0"
            f"/drives/{settings.graph_excel_drive_id}"
            f"/items/{settings.graph_excel_item_id}"
            f"/workbook{workbook_path}"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with (
            aiohttp.ClientSession() as session,
            session.request(method, url, headers=headers, json=json_body) as resp,
        ):
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"Graph workbook request failed ({resp.status}): {body}")
            if resp.content_length == 0:
                logger.info(
                    "Graph workbook request %s %s completed in %.3fs",
                    method,
                    workbook_path,
                    perf_counter() - started,
                )
                return {}
            text = await resp.text()
            result = {} if not text else await resp.json()
            logger.info(
                "Graph workbook request %s %s completed in %.3fs",
                method,
                workbook_path,
                perf_counter() - started,
            )
            return result

    # ------------------------------------------------------------------
    # Excel tracker helpers
    # ------------------------------------------------------------------

    async def find_employee_in_tracker(self, employee_email: str) -> dict[str, Any]:
        """Return tracker row details for the given email."""
        try:
            rows = await self._used_range_rows()
            if not rows:
                return {"found": False, "row_id": "", "stages": {}}

            for i, row in enumerate(rows[1:], start=2):  # skip header row
                if len(row) > _COL_EMAIL and str(row[_COL_EMAIL]).lower() == employee_email.lower():
                    stages = _row_to_stages(row)
                    return {
                        "found": True,
                        "row_id": str(i),
                        "name": str(row[_COL_NAME]) if len(row) > _COL_NAME else "",
                        "email": str(row[_COL_EMAIL]) if len(row) > _COL_EMAIL else "",
                        "location": str(row[_COL_LOCATION]) if len(row) > _COL_LOCATION else "",
                        "start_date": str(row[_COL_START_DATE]) if len(row) > _COL_START_DATE else "",
                        "department": str(row[_COL_DEPARTMENT]) if len(row) > _COL_DEPARTMENT else "",
                        "manager_email": str(row[_COL_MANAGER_EMAIL]) if len(row) > _COL_MANAGER_EMAIL else "",
                        "stages": stages,
                        "status": _latest_active_stage(stages),
                    }

            return {"found": False, "row_id": "", "stages": {}}
        except Exception as exc:
            logger.exception("find_employee_in_tracker failed")
            return {"found": False, "row_id": "", "stages": {}, "error": str(exc)}

    async def add_employee_to_tracker(
        self,
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
        location: str = "",
    ) -> dict[str, Any]:
        """Append a new row to the Excel tracker."""
        try:
            rows = await self._used_range_rows()
            next_row = len(rows) + 1 if rows else 2

            row = [""] * len(HEADER_ROW)
            row[_COL_NAME] = name
            row[_COL_EMAIL] = email
            row[_COL_LOCATION] = location
            row[_COL_START_DATE] = start_date
            row[_COL_DEPARTMENT] = department
            row[_COL_MANAGER_EMAIL] = manager_email
            row[STAGES["Added to Tracker"]] = _today()

            logger.info(
                "Writing Excel row %s with direct mapping values=%s",
                next_row,
                row,
            )

            range_address = quote(f"A{next_row}:O{next_row}")
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(settings.graph_excel_sheet_name)}/range(address='{range_address}')",
                {"values": [row]},
            )
            return {"success": True, "row_id": str(next_row)}
        except Exception as exc:
            logger.exception("add_employee_to_tracker failed")
            return {"success": False, "row_id": "", "error": str(exc)}

    async def update_stage(
        self,
        employee_email: str,
        stage_name: str,
        value: str | None = None,
    ) -> dict[str, Any]:
        """Record a completion date for a tracker stage."""
        if stage_name not in STAGES:
            return {
                "success": False,
                "error": f"Unknown stage '{stage_name}'. Valid stages: {list(STAGES)}",
            }

        employee = await self.find_employee_in_tracker(employee_email)
        if not employee.get("found"):
            return {"success": False, "error": f"Employee {employee_email} not found in tracker"}

        try:
            row_id = employee["row_id"]
            col_letter = chr(ord("A") + STAGES[stage_name])
            cell_value = value if value is not None else _today()
            range_address = quote(f"{col_letter}{row_id}")
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(settings.graph_excel_sheet_name)}/range(address='{range_address}')",
                {"values": [[cell_value]]},
            )
            return {
                "success": True,
                "employee_email": employee_email,
                "stage": stage_name,
                "value": cell_value,
            }
        except Exception as exc:
            logger.exception("update_stage failed")
            return {"success": False, "error": str(exc)}

    async def update_tracker_status(self, row_id: str, new_status: str) -> dict[str, Any]:
        """Legacy shim retained for compatibility."""
        logger.warning("update_tracker_status called with row_id=%s; prefer update_stage", row_id)
        stage_name = new_status if new_status in STAGES else "Added to Tracker"
        rows = await self._used_range_rows()
        index = int(row_id) - 1
        if index < 1 or index >= len(rows):
            return {"success": False, "row_id": row_id, "error": "Row not found"}
        employee_email = str(rows[index][_COL_EMAIL]) if len(rows[index]) > _COL_EMAIL else ""
        if not employee_email:
            return {"success": False, "row_id": row_id, "error": "Email not found for row"}
        result = await self.update_stage(employee_email, stage_name)
        return {"row_id": row_id, **result}

    async def list_all_employees(self) -> dict[str, Any]:
        """List all employees in the Excel tracker."""
        try:
            rows = await self._used_range_rows()
            employees = []
            for row in rows[1:]:
                if len(row) <= _COL_EMAIL or not row[_COL_EMAIL]:
                    continue
                employees.append(
                    {
                        "name": str(row[_COL_NAME]) if len(row) > _COL_NAME else "",
                        "email": str(row[_COL_EMAIL]),
                        "location": str(row[_COL_LOCATION]) if len(row) > _COL_LOCATION else "",
                        "start_date": str(row[_COL_START_DATE]) if len(row) > _COL_START_DATE else "",
                        "department": str(row[_COL_DEPARTMENT]) if len(row) > _COL_DEPARTMENT else "",
                        "stages": _row_to_stages(row),
                    }
                )
            return {"success": True, "employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.exception("list_all_employees failed")
            return {"success": False, "employees": [], "count": 0, "error": str(exc)}

    async def get_employee_stages(self, employee_email: str) -> dict[str, Any]:
        """Return stage details for one employee."""
        result = await self.find_employee_in_tracker(employee_email)
        if not result.get("found"):
            return {"found": False, "employee_email": employee_email, "stages": {}}
        return {
            "found": True,
            "employee_email": employee_email,
            "name": result.get("name", ""),
            "start_date": result.get("start_date", ""),
            "stages": result.get("stages", {}),
        }

    # ------------------------------------------------------------------
    # Forms
    # ------------------------------------------------------------------

    async def get_form_submission_by_id(self, submission_id: str) -> dict[str, Any]:
        """Fetch a specific Forms response. Uses the Graph beta endpoint."""
        import aiohttp
        from azure.identity.aio import ClientSecretCredential as AsyncCred

        cred = AsyncCred(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        try:
            token = await cred.get_token("https://graph.microsoft.com/.default")
            url = (
                f"https://graph.microsoft.com/v1.0/forms/{settings.graph_forms_form_id}"
                f"/responses/{submission_id}"
            )
            async with aiohttp.ClientSession() as session, session.get(
                url, headers={"Authorization": f"Bearer {token.token}"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"found": True, "data": data}
                return {"found": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("get_form_submission_by_id failed")
            return {"found": False, "error": str(exc)}
        finally:
            await cred.close()

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    async def send_teams_channel_notification(
        self, channel_id: str, message: str, card: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Post a message to a Teams channel via Agents SDK proactive messaging."""
        started = perf_counter()
        from onboarding_agent.integrations.adaptive_cards import generic_notification_card
        from onboarding_agent.integrations.teams_proactive import send_proactive_message

        if card is None:
            card = generic_notification_card(title="Onboarding Agent", message=message)
        result = await send_proactive_message(channel_id, message, card=card)
        logger.info(
            "Teams channel notification to %s completed in %.3fs success=%s",
            channel_id,
            perf_counter() - started,
            result.get("success", False),
        )
        return result

    async def send_teams_direct_message(self, user_id: str, message: str) -> dict[str, Any]:
        """Create or reuse a 1:1 chat and post a message."""
        import aiohttp
        from azure.identity.aio import ClientSecretCredential as AsyncCred

        cred = AsyncCred(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        try:
            token = await cred.get_token("https://graph.microsoft.com/.default")
            headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}

            async with aiohttp.ClientSession() as session:
                chat_payload = {
                    "chatType": "oneOnOne",
                    "members": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_id}",
                        }
                    ],
                }
                async with session.post(
                    "https://graph.microsoft.com/v1.0/chats",
                    json=chat_payload,
                    headers=headers,
                ) as resp:
                    chat_data = await resp.json()
                    chat_id = chat_data.get("id", "")

                msg_payload = {"body": {"content": message}}
                async with session.post(
                    f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages",
                    json=msg_payload,
                    headers=headers,
                ) as resp:
                    if resp.status in (200, 201):
                        return {"success": True, "chat_id": chat_id}
                    return {"success": False, "chat_id": chat_id, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("send_teams_direct_message failed")
            return {"success": False, "chat_id": "", "error": str(exc)}
        finally:
            await cred.close()

    async def send_teams_reply(self, activity_id: str, message: str) -> dict[str, Any]:
        """Reply in a Teams thread."""
        return await self.send_teams_channel_notification(settings.teams_channel_id, message)
