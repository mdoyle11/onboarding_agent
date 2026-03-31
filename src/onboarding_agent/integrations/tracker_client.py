"""Excel onboarding tracker operations."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from onboarding_agent.config import settings
from onboarding_agent.integrations.graph_workbook import (
    _COL_DEPARTMENT,
    _COL_EMAIL,
    _COL_LOCATION,
    _COL_MANAGER_EMAIL,
    _COL_NAME,
    _COL_START_DATE,
    HEADER_ROW,
    STAGES,
    WorkbookGraphClient,
    _latest_active_stage,
    _row_to_stages,
    _today,
)

logger = logging.getLogger(__name__)


class TrackerClient(WorkbookGraphClient):
    """Workbook-backed onboarding tracker operations."""

    async def find_employee_in_tracker(self, employee_email: str) -> dict[str, Any]:
        try:
            rows = await self._used_range_rows()
            if not rows:
                return {"found": False, "row_id": "", "stages": {}}

            for i, row in enumerate(rows[1:], start=2):
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

            logger.info("Writing Excel row %s with direct mapping values=%s", next_row, row)

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
