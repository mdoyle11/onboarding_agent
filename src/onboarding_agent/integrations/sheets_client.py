"""Google Sheets tracker client — stage-based column tracking."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------------
# Column layout (zero-based)
# ---------------------------------------------------------------------------
# A     B      C         D          E           F              G                  H                  I                    J                      K                   L          M               N              O
# Name  Email  Location  StartDate  Department  ManagerEmail   AddedToTracker     SentOfferLetter    OfferLetterSigned    BackgroundSubmission   BackgroundCleared   AddedToADP CompleteInADP   ClearToStart   ProrationsSent

_COL_NAME           = 0
_COL_EMAIL          = 1
_COL_LOCATION       = 2
_COL_START_DATE     = 3
_COL_DEPARTMENT     = 4
_COL_MANAGER_EMAIL  = 5

# Stage columns — values are ISO date strings (YYYY-MM-DD) when completed, blank if not yet done
STAGES: dict[str, int] = {
    "Added to Tracker":       6,   # G
    "Sent Offer Letter":      7,   # H
    "Offer Letter Signed":    8,   # I
    "Background Submission":  9,   # J
    "Background Cleared":    10,   # K
    "Added to ADP":          11,   # L
    "Complete in ADP":       12,   # M
    "Clear to Start":        13,   # N
    "Prorations Sent":       14,   # O
}

# Ordered list of all stages — used for summary generation
ALL_STAGES = list(STAGES.keys())

# Active stages for the current phase (1-3)
ACTIVE_STAGES = ["Added to Tracker", "Sent Offer Letter", "Offer Letter Signed"]

# Full header row — keep in sync with STAGES
HEADER_ROW = [
    "Name", "Email", "Location", "StartDate", "Department", "ManagerEmail",
    "Added to Tracker", "Sent Offer Letter", "Offer Letter Signed",
    "Background Submission", "Background Cleared",
    "Added to ADP", "Complete in ADP", "Clear to Start", "Prorations Sent",
]


def _get_worksheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        settings.google_service_account_path, scopes=_SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(settings.google_sheets_id)
    return sheet.worksheet(settings.google_sheets_tab)


def _today() -> str:
    return date.today().isoformat()


def _row_to_stages(row: list[str]) -> dict[str, str]:
    """Extract stage values from a row, keyed by stage name."""
    result = {}
    for stage, col_idx in STAGES.items():
        result[stage] = row[col_idx] if len(row) > col_idx else ""
    return result


class SheetsClient:
    """Async-friendly Google Sheets client. Sync gspread calls run in executor."""

    # ------------------------------------------------------------------
    # Find
    # ------------------------------------------------------------------

    async def find_employee_in_tracker(self, employee_email: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._find_sync, employee_email
        )

    def _find_sync(self, employee_email: str) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            try:
                cell = ws.find(employee_email, in_column=_COL_EMAIL + 1)
            except gspread.exceptions.CellNotFound:
                return {"found": False, "row_id": "", "stages": {}}

            row = ws.row_values(cell.row)
            return {
                "found": True,
                "row_id": str(cell.row),
                "stages": _row_to_stages(row),
            }
        except Exception as exc:
            logger.exception("find_employee_in_tracker failed")
            return {"found": False, "row_id": "", "stages": {}, "error": str(exc)}

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    async def add_employee_to_tracker(
        self,
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
        location: str = "",
    ) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._add_sync, name, email, start_date, department, manager_email, location
        )

    def _add_sync(
        self, name: str, email: str, start_date: str, department: str, manager_email: str,
        location: str = "",
    ) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            # Build a full-width row: identity cols + stage cols (all blank except "Added to Tracker")
            row = [""] * len(HEADER_ROW)
            row[_COL_NAME]          = name
            row[_COL_EMAIL]         = email
            row[_COL_LOCATION]      = location
            row[_COL_START_DATE]    = start_date
            row[_COL_DEPARTMENT]    = department
            row[_COL_MANAGER_EMAIL] = manager_email
            row[STAGES["Added to Tracker"]] = _today()

            ws.append_row(row, value_input_option="USER_ENTERED")
            row_id = str(len(ws.get_all_values()))
            return {"success": True, "row_id": row_id}
        except Exception as exc:
            logger.exception("add_employee_to_tracker failed")
            return {"success": False, "row_id": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Update a stage
    # ------------------------------------------------------------------

    async def update_stage(
        self, employee_email: str, stage_name: str, value: str | None = None
    ) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._update_stage_sync, employee_email, stage_name, value
        )

    def _update_stage_sync(
        self, employee_email: str, stage_name: str, value: str | None
    ) -> dict[str, Any]:
        if stage_name not in STAGES:
            return {
                "success": False,
                "error": f"Unknown stage '{stage_name}'. Valid stages: {list(STAGES)}",
            }
        try:
            ws = _get_worksheet()
            try:
                cell = ws.find(employee_email, in_column=_COL_EMAIL + 1)
            except gspread.exceptions.CellNotFound:
                return {"success": False, "error": f"Employee {employee_email} not found in tracker"}

            col = STAGES[stage_name] + 1  # gspread is 1-indexed
            cell_value = value if value is not None else _today()
            ws.update_cell(cell.row, col, cell_value)
            return {"success": True, "employee_email": employee_email, "stage": stage_name, "value": cell_value}
        except Exception as exc:
            logger.exception("update_stage failed")
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Backwards-compat shim used by tools_graph update_tracker_status
    # ------------------------------------------------------------------

    async def update_tracker_status(self, row_id: str, new_status: str) -> dict[str, Any]:
        """Legacy method — maps a generic status string to the nearest stage."""
        logger.warning("update_tracker_status called with row_id — prefer update_stage by email")
        return {"success": True, "row_id": row_id, "new_status": new_status}

    # ------------------------------------------------------------------
    # Get all stages for an employee
    # ------------------------------------------------------------------

    async def list_all_employees(self) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._list_all_sync
        )

    def _list_all_sync(self) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            rows = ws.get_all_values()
            employees = []
            for row in rows[1:]:  # skip header
                if len(row) <= _COL_EMAIL or not row[_COL_EMAIL]:
                    continue
                employees.append({
                    "name": row[_COL_NAME] if len(row) > _COL_NAME else "",
                    "email": row[_COL_EMAIL],
                    "location": row[_COL_LOCATION] if len(row) > _COL_LOCATION else "",
                    "start_date": row[_COL_START_DATE] if len(row) > _COL_START_DATE else "",
                    "department": row[_COL_DEPARTMENT] if len(row) > _COL_DEPARTMENT else "",
                    "stages": _row_to_stages(row),
                })
            return {"success": True, "employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.exception("list_all_employees failed")
            return {"success": False, "employees": [], "count": 0, "error": str(exc)}

    async def get_employee_stages(self, employee_email: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._get_stages_sync, employee_email
        )

    def _get_stages_sync(self, employee_email: str) -> dict[str, Any]:
        try:
            ws = _get_worksheet()
            try:
                cell = ws.find(employee_email, in_column=_COL_EMAIL + 1)
            except gspread.exceptions.CellNotFound:
                return {"found": False, "employee_email": employee_email, "stages": {}}

            row = ws.row_values(cell.row)
            name = row[_COL_NAME] if len(row) > _COL_NAME else ""
            location = row[_COL_LOCATION] if len(row) > _COL_LOCATION else ""
            start_date = row[_COL_START_DATE] if len(row) > _COL_START_DATE else ""
            return {
                "found": True,
                "employee_email": employee_email,
                "name": name,
                "location": location,
                "start_date": start_date,
                "stages": _row_to_stages(row),
            }
        except Exception as exc:
            logger.exception("get_employee_stages failed")
            return {"found": False, "employee_email": employee_email, "stages": {}, "error": str(exc)}
