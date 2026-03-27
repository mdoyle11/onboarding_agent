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
# Name  Email  Location  StartDate  Department  ManagerEmail   AddedToTracker     AddedToStaffRoster
# I                  J                    K                      L                 M          N               O              P
# SentOfferLetter    OfferLetterSigned    BackgroundSubmission   BackgroundCleared AddedToADP CompleteInADP   ClearToStart   ProrationsSent

_COL_NAME = 0
_COL_EMAIL = 1
_COL_LOCATION = 2
_COL_START_DATE = 3
_COL_DEPARTMENT = 4
_COL_MANAGER_EMAIL = 5

STAGES: dict[str, int] = {
    "Added to Tracker": 6,
    "Added to Staff Roster": 7,
    "Sent Offer Letter": 8,
    "Offer Letter Signed": 9,
    "Background Submission": 10,
    "Background Cleared": 11,
    "Added to ADP": 12,
    "Complete in ADP": 13,
    "Clear to Start": 14,
    "Prorations Sent": 15,
}

ALL_STAGES = list(STAGES.keys())
ACTIVE_STAGES = ["Added to Tracker", "Added to Staff Roster", "Sent Offer Letter", "Offer Letter Signed"]

HEADER_ROW = [
    "Name",
    "Email",
    "Location",
    "StartDate",
    "Department",
    "ManagerEmail",
    "Added to Tracker",
    "Added to Staff Roster",
    "Sent Offer Letter",
    "Offer Letter Signed",
    "Background Submission",
    "Background Cleared",
    "Added to ADP",
    "Complete in ADP",
    "Clear to Start",
    "Prorations Sent",
]

_ROSTER_REQUIRED_ALIASES = {
    "name": {"employee name", "name"},
    "email": {"employee email", "email"},
    "group": {"group", "job category", "category"},
}

_ROSTER_OPTIONAL_ALIASES = {
    "start_date": {"start date", "startdate"},
    "department": {"department"},
    "manager_email": {"manager email", "manageremail"},
    "location": {"location"},
}

_CAPACITY_ALIASES = {
    "group": {"group", "job category", "category"},
    "capacity": {"capacity", "max capacity", "maxcapacity"},
}


def _today() -> str:
    return date.today().isoformat()


def _normalize_header(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def _column_letter(index: int) -> str:
    result = ""
    current = index + 1
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _header_map(header_row: list[Any], aliases: dict[str, set[str]]) -> dict[str, int]:
    normalized = {_normalize_header(value): idx for idx, value in enumerate(header_row)}
    resolved: dict[str, int] = {}
    for key, names in aliases.items():
        for name in names:
            idx = normalized.get(_normalize_header(name))
            if idx is not None:
                resolved[key] = idx
                break
    return resolved


def _cell(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


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

    async def _used_range_rows(
        self,
        *,
        drive_id: str | None = None,
        item_id: str | None = None,
        sheet_name: str | None = None,
    ) -> list[list[Any]]:
        data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(sheet_name or settings.graph_excel_sheet_name)}/usedRange(valuesOnly=true)",
            drive_id=drive_id,
            item_id=item_id,
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
        *,
        drive_id: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        token = await self._graph_access_token()
        url = (
            "https://graph.microsoft.com/v1.0"
            f"/drives/{drive_id or settings.graph_excel_drive_id}"
            f"/items/{item_id or settings.graph_excel_item_id}"
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

    def _staff_roster_workbook(self, location: str) -> dict[str, str]:
        workbook = settings.staff_roster_workbook(location)
        if workbook is None:
            raise ValueError(f"No staff roster workbook configured for location '{location}'")
        if not workbook.get("drive_id") or not workbook.get("item_id"):
            raise ValueError(f"Staff roster workbook for '{location}' is missing drive_id or item_id")
        return workbook

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

            range_address = quote(f"A{next_row}:P{next_row}")
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
    # Staff Roster
    # ------------------------------------------------------------------

    async def check_staff_roster_capacity(self, location: str, job_category: str) -> dict[str, Any]:
        """Return current and max capacity for a location/category staff roster."""
        try:
            workbook = self._staff_roster_workbook(location)
            capacity_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["capacity_sheet_name"],
            )
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )

            if not capacity_rows:
                return {"success": False, "error": "Capacity sheet is empty"}
            if not roster_rows:
                return {"success": False, "error": "Roster sheet is empty"}

            capacity_header = _header_map(capacity_rows[0], _CAPACITY_ALIASES)
            if "group" not in capacity_header or "capacity" not in capacity_header:
                return {"success": False, "error": "Capacity sheet must contain Group and Capacity columns"}

            roster_aliases = {**_ROSTER_REQUIRED_ALIASES, **_ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in _ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {"success": False, "error": f"Roster sheet is missing required columns: {missing_list}"}

            normalized_category = job_category.strip().lower()
            max_capacity: int | None = None
            for row in capacity_rows[1:]:
                if _cell(row, capacity_header.get("group")).lower() != normalized_category:
                    continue
                capacity_text = _cell(row, capacity_header.get("capacity"))
                if capacity_text:
                    max_capacity = int(float(capacity_text))
                break

            if max_capacity is None:
                return {
                    "success": False,
                    "location": location,
                    "job_category": job_category,
                    "error": f"No capacity row found for category '{job_category}'",
                }

            current_count = 0
            for row in roster_rows[1:]:
                email = _cell(row, roster_header.get("email"))
                group = _cell(row, roster_header.get("group"))
                if not email or not group:
                    continue
                if group.lower() == normalized_category:
                    current_count += 1

            return {
                "success": True,
                "location": location,
                "job_category": job_category,
                "current_count": current_count,
                "max_capacity": max_capacity,
                "remaining_capacity": max_capacity - current_count,
                "has_capacity": current_count < max_capacity,
            }
        except Exception as exc:
            logger.exception("check_staff_roster_capacity failed")
            return {
                "success": False,
                "location": location,
                "job_category": job_category,
                "error": str(exc),
            }

    async def add_employee_to_staff_roster(self, employee_email: str, job_category: str) -> dict[str, Any]:
        """Append an employee to the configured location staff roster if capacity allows."""
        try:
            employee = await self.find_employee_in_tracker(employee_email)
            if not employee.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": job_category,
                    "error": f"Employee {employee_email} not found in onboarding tracker",
                }

            location = str(employee.get("location", "") or "")
            workbook = self._staff_roster_workbook(location)
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not roster_rows:
                return {"success": False, "error": "Roster sheet is empty"}

            roster_aliases = {**_ROSTER_REQUIRED_ALIASES, **_ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in _ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {"success": False, "error": f"Roster sheet is missing required columns: {missing_list}"}

            normalized_email = employee_email.strip().lower()
            for index, row in enumerate(roster_rows[1:], start=2):
                if _cell(row, roster_header.get("email")).lower() == normalized_email:
                    return {
                        "success": True,
                        "employee_email": employee_email,
                        "job_category": job_category,
                        "location": location,
                        "row_id": str(index),
                        "already_exists": True,
                    }

            capacity = await self.check_staff_roster_capacity(location, job_category)
            if not capacity.get("success"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": job_category,
                    "location": location,
                    "error": str(capacity.get("error", "Capacity check failed")),
                }
            if not capacity.get("has_capacity"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": job_category,
                    "location": location,
                    "current_count": capacity.get("current_count", 0),
                    "max_capacity": capacity.get("max_capacity", 0),
                    "error": f"Category '{job_category}' at {location} is at capacity",
                }

            row_width = max(len(roster_rows[0]), max(roster_header.values()) + 1)
            next_row = len(roster_rows) + 1
            new_row = [""] * row_width
            new_row[roster_header["name"]] = str(employee.get("name", "") or "")
            new_row[roster_header["email"]] = employee_email
            new_row[roster_header["group"]] = job_category

            optional_values = {
                "start_date": str(employee.get("start_date", "") or ""),
                "department": str(employee.get("department", "") or ""),
                "manager_email": str(employee.get("manager_email", "") or ""),
                "location": location,
            }
            for key, value in optional_values.items():
                idx = roster_header.get(key)
                if idx is not None:
                    new_row[idx] = value

            logger.info(
                "Writing staff roster row %s for %s/%s values=%s",
                next_row,
                location,
                job_category,
                new_row,
            )
            range_address = quote(f"A{next_row}:{_column_letter(len(new_row) - 1)}{next_row}")
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(workbook['roster_sheet_name'])}/range(address='{range_address}')",
                {"values": [new_row]},
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
            )
            return {
                "success": True,
                "employee_email": employee_email,
                "job_category": job_category,
                "location": location,
                "row_id": str(next_row),
                "already_exists": False,
                "remaining_capacity": int(capacity.get("remaining_capacity", 0)) - 1,
            }
        except Exception as exc:
            logger.exception("add_employee_to_staff_roster failed")
            return {
                "success": False,
                "employee_email": employee_email,
                "job_category": job_category,
                "error": str(exc),
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
