"""Staff roster workbook operations."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from onboarding_agent.integrations.workbook.client import WorkbookGraphClient
from onboarding_agent.integrations.workbook.helpers import (
    cell as _cell,
)
from onboarding_agent.integrations.workbook.helpers import (
    column_letter as _column_letter,
)
from onboarding_agent.integrations.workbook.helpers import (
    header_map as _header_map,
)
from onboarding_agent.integrations.workbook.schema import (
    CAPACITY_ALIASES,
    ROSTER_OPTIONAL_ALIASES,
    ROSTER_REQUIRED_ALIASES,
)
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

logger = logging.getLogger(__name__)


class StaffRosterClient(WorkbookGraphClient):
    """Workbook-backed staff roster and capacity operations."""

    async def check_staff_roster_capacity(self, location: str, job_category: str) -> dict[str, Any]:
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

            capacity_header = _header_map(capacity_rows[0], CAPACITY_ALIASES)
            if "group" not in capacity_header or "capacity" not in capacity_header:
                return {"success": False, "error": "Capacity sheet must contain Group and Capacity columns"}

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
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

    async def add_employee_to_staff_roster(
        self,
        employee_email: str,
        job_category: str,
        *,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        try:
            employee = await TrackerClient().find_employee_in_tracker(
                employee_email,
                location=location,
                job_title=job_title,
                status_change=status_change,
            )
            if not employee.get("found"):
                matches = employee.get("matches", [])
                if employee.get("multiple_matches") and isinstance(matches, list) and matches:
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "job_category": job_category,
                        "multiple_matches": True,
                        "matches": matches,
                        "error": (
                            f"Multiple onboarding tracker rows matched {employee_email}. "
                            "Pass location, job_title, and status_change to disambiguate."
                        ),
                    }
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

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
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
                "position": str(employee.get("position", "") or employee.get("job_title", "") or ""),
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
