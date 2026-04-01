"""Shared Microsoft Graph workbook helpers and onboarding tracker constants."""

from __future__ import annotations

import logging
import re
from datetime import date
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote

import aiohttp
from azure.identity.aio import ClientSecretCredential

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_ADDRESS_ROW_RE = re.compile(r"[A-Z]+(\d+)")

_SCOPES = ["https://graph.microsoft.com/.default"]

TRACKER_REQUIRED_ALIASES = {
    "staff_name": {"staff name", "name", "employee name"},
    "staff_email": {"staff email", "email", "employee email"},
    "work_location": {"work location", "location"},
    "requested_start_date": {"requested start date", "start date", "startdate"},
}

TRACKER_OPTIONAL_ALIASES = {
    "requesting_manager": {"requesting manager", "manager", "manager email"},
    "status_change": {"status change", "status"},
    "staff_phone": {"staff phone #", "staff phone", "phone"},
    "job_title": {"job title", "title", "position"},
    "education_level": {"education level"},
    "supplements": {"supplements"},
    "license_number": {"license #", "license"},
    "uploaded_credentials": {"uploaded credentials", "credentials"},
    "compensation": {"compensation"},
    "employment_type": {"employment type"},
    "contract_term": {"contract term"},
}

STAGE_NAMES = [
    "Added to Tracker",
    "Added to Staff Roster",
    "Sent Offer Letter",
    "Offer Letter Signed",
    "Background Submission",
    "Background Cleared",
    "Added to ADP",
    "Employee Complete ADP Profile",
    "Completed in ADP",
    "Proration",
    "Clear to Start",
    "Drug Screening",
]

STAGE_ALIASES = {
    "Complete in ADP": "Completed in ADP",
    "Prorations Sent": "Proration",
    "Start Date": "Clear to Start",
}

ALL_STAGES = list(STAGE_NAMES)
ACTIVE_STAGES = ["Added to Tracker", "Added to Staff Roster", "Sent Offer Letter", "Offer Letter Signed"]

HEADER_ROW = [
    "Requesting Manager",
    "Work Location",
    "Status Change",
    "Staff Name",
    "Staff Email",
    "Staff Phone #",
    "Job Title",
    "Requested Start Date",
    "Education Level",
    "Supplements",
    "License #",
    "Uploaded Credentials",
    "Compensation",
    "Employment Type",
    "Contract Term",
] + STAGE_NAMES

ROSTER_REQUIRED_ALIASES = {
    "name": {"employee name", "name"},
    "email": {"employee email", "email"},
    "group": {"group", "job category", "category"},
}

ROSTER_OPTIONAL_ALIASES = {
    "start_date": {"start date", "startdate"},
    "position": {"position"},
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


def _row_to_stages(row: list[Any], stage_indices: dict[str, int]) -> dict[str, str]:
    return {
        stage: str(row[col_idx]) if len(row) > col_idx and row[col_idx] is not None else ""
        for stage, col_idx in stage_indices.items()
    }


def _latest_active_stage(stages: dict[str, str]) -> str:
    latest = ""
    for stage in ACTIVE_STAGES:
        if stages.get(stage):
            latest = stage
    return latest


def _stage_column_map(header_row: list[Any]) -> dict[str, int]:
    normalized = {_normalize_header(value): idx for idx, value in enumerate(header_row)}
    resolved: dict[str, int] = {}
    for stage in STAGE_NAMES:
        idx = normalized.get(_normalize_header(stage))
        if idx is not None:
            resolved[stage] = idx
    return resolved


def _resolve_stage_name(stage_name: str, stage_indices: dict[str, int]) -> str | None:
    direct = stage_name.strip()
    if direct in stage_indices:
        return direct
    alias = STAGE_ALIASES.get(direct, "")
    if alias and alias in stage_indices:
        return alias
    return None


class WorkbookGraphClient:
    """Shared Graph workbook operations for tracker and roster clients."""

    @staticmethod
    def _start_row_from_address(address: str) -> int:
        if not address:
            return 1
        match = _ADDRESS_ROW_RE.search(address.split("!", 1)[-1])
        if match is None:
            return 1
        try:
            return int(match.group(1))
        except ValueError:
            return 1

    async def _tracker_rows_with_start_row(self) -> tuple[int, list[list[Any]]]:
        """Return tracker rows and the worksheet row number of the header row."""
        table_name = settings.graph_excel_table_name.strip()
        if table_name:
            try:
                table_data = await self._graph_workbook_request(
                    "GET",
                    f"/tables/{quote(table_name)}/range",
                )
                table_values = table_data.get("values", []) if isinstance(table_data, dict) else []
                if table_values:
                    return (
                        self._start_row_from_address(str(table_data.get("address", "") or "")),
                        cast(list[list[Any]], table_values),
                    )
            except Exception:
                logger.warning(
                    "Falling back to usedRange for tracker reads; table '%s' query failed",
                    table_name,
                    exc_info=True,
                )

        used_range_data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(settings.graph_excel_sheet_name)}/usedRange(valuesOnly=true)",
        )
        used_range_values = used_range_data.get("values", []) if isinstance(used_range_data, dict) else []
        if not used_range_values:
            return 1, []
        return (
            self._start_row_from_address(str(used_range_data.get("address", "") or "")),
            cast(list[list[Any]], used_range_values),
        )

    async def _used_range_rows(
        self,
        *,
        drive_id: str | None = None,
        item_id: str | None = None,
        sheet_name: str | None = None,
    ) -> list[list[Any]]:
        if drive_id is None and item_id is None and sheet_name is None:
            _, rows = await self._tracker_rows_with_start_row()
            return rows

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
