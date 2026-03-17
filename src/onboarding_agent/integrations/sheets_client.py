"""Google Sheets tracker client — drop-in replacement for the Excel tracker methods."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Column indices (zero-based) matching the Excel tracker layout
_COL_NAME = 0
_COL_EMAIL = 1
_COL_START_DATE = 2
_COL_DEPARTMENT = 3
_COL_MANAGER_EMAIL = 4
_COL_STATUS = 5


def _get_worksheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        settings.google_service_account_path, scopes=_SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(settings.google_sheets_id)
    return sheet.worksheet(settings.google_sheets_tab)


class SheetsClient:
    """Async-friendly Google Sheets client. Sync gspread calls run in executor."""

    async def find_employee_in_tracker(self, employee_email: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._find_sync, employee_email
        )

    def _find_sync(self, employee_email: str) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            try:
                cell = ws.find(employee_email, in_column=_COL_EMAIL + 1)  # gspread is 1-indexed
            except gspread.exceptions.CellNotFound:
                return {"found": False, "row_id": "", "status": ""}

            row = ws.row_values(cell.row)
            status = row[_COL_STATUS] if len(row) > _COL_STATUS else ""
            return {"found": True, "row_id": str(cell.row), "status": status}
        except Exception as exc:
            logger.exception("find_employee_in_tracker failed")
            return {"found": False, "row_id": "", "status": "", "error": str(exc)}

    async def add_employee_to_tracker(
        self,
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
    ) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._add_sync, name, email, start_date, department, manager_email
        )

    def _add_sync(
        self, name: str, email: str, start_date: str, department: str, manager_email: str
    ) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            ws.append_row(
                [name, email, start_date, department, manager_email, "Pending"],
                value_input_option="USER_ENTERED",
            )
            # Return the row number of the newly appended row
            row_id = str(len(ws.get_all_values()))
            return {"success": True, "row_id": row_id}
        except Exception as exc:
            logger.exception("add_employee_to_tracker failed")
            return {"success": False, "row_id": "", "error": str(exc)}

    async def update_tracker_status(self, row_id: str, new_status: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._update_sync, row_id, new_status
        )

    def _update_sync(self, row_id: str, new_status: str) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            ws.update_cell(int(row_id), _COL_STATUS + 1, new_status)  # 1-indexed
            return {"success": True, "row_id": row_id, "new_status": new_status}
        except Exception as exc:
            logger.exception("update_tracker_status failed")
            return {"success": False, "row_id": row_id, "error": str(exc)}
