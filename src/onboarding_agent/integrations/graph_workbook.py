"""Shared Microsoft Graph workbook helpers and onboarding tracker constants."""

from __future__ import annotations

import logging
from datetime import date
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote

import aiohttp
from azure.identity.aio import ClientSecretCredential

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://graph.microsoft.com/.default"]

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

ROSTER_REQUIRED_ALIASES = {
    "name": {"employee name", "name"},
    "email": {"employee email", "email"},
    "group": {"group", "job category", "category"},
}

ROSTER_OPTIONAL_ALIASES = {
    "start_date": {"start date", "startdate"},
    "department": {"department"},
    "manager_email": {"manager email", "manageremail"},
    "location": {"location"},
}

CAPACITY_ALIASES = {
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


class WorkbookGraphClient:
    """Shared Graph workbook operations for tracker and roster clients."""

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
