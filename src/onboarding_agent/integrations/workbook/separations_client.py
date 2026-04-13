"""Separations sheet operations (append-only log)."""

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
from onboarding_agent.integrations.workbook.helpers import (
    today_iso as _today_iso,
)
from onboarding_agent.integrations.workbook.schema import (
    SEPARATIONS_OPTIONAL_ALIASES,
    SEPARATIONS_REQUIRED_ALIASES,
)

logger = logging.getLogger(__name__)

_ALL_ALIASES = {**SEPARATIONS_REQUIRED_ALIASES, **SEPARATIONS_OPTIONAL_ALIASES}


class SeparationsClient(WorkbookGraphClient):
    """Append-only client for the Separations sheet in staff roster workbooks."""

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _separation_status_label(status_change: str) -> str:
        normalized = SeparationsClient._normalized(status_change)
        if "transfer" in normalized and "out" in normalized:
            return "Transfer Out"
        if "separation" in normalized:
            return "Separation"
        return str(status_change or "").strip()

    async def add_separation_record(
        self,
        employee_email: str,
        *,
        location: str,
        employee_name: str = "",
        status_change: str = "",
        job_title: str = "",
        job_category: str = "",
        effective_date: str = "",
        manager_email: str = "",
        notes: str = "",
        roster_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a separation record to the Separations sheet.

        If *roster_data* is provided (from ``find_employee_in_staff_roster``),
        column values are populated from the roster snapshot so the separation
        row mirrors the employee's roster state at the time of departure.
        """
        try:
            workbook = self._staff_roster_workbook(location)
            sheet_name = workbook.get("separations_sheet_name", "Separations")

            rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=sheet_name,
            )

            if not rows:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "error": f"Separations sheet '{sheet_name}' is empty or does not exist.",
                }

            header = _header_map(rows[0], _ALL_ALIASES)
            missing = [k for k in SEPARATIONS_REQUIRED_ALIASES if k not in header]
            if missing:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "error": f"Separations sheet is missing required columns: {', '.join(missing)}",
                }

            incoming_email = self._normalized(employee_email)
            incoming_personal_email = self._normalized(str((roster_data or {}).get("personal_email", "") or employee_email))
            incoming_group = self._normalized(str((roster_data or {}).get("job_category", "") or job_category))
            incoming_position = self._normalized(str((roster_data or {}).get("position", "") or job_title))
            separation_status = self._separation_status_label(status_change)
            if not separation_status:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "needs_clarification": True,
                    "error": "Please specify whether this move is a Separation or Transfer Out.",
                }

            # Duplicate check: allow multiple separation records for the same
            # employee when they refer to different roles/categories.
            for row in rows[1:]:
                row_email = self._normalized(_cell(row, header.get("email")))
                row_personal_email = self._normalized(_cell(row, header.get("personal_email")))
                row_type = self._normalized(_cell(row, header.get("separation_type")))
                row_group = self._normalized(_cell(row, header.get("group")))
                row_position = self._normalized(_cell(row, header.get("position")))
                if (
                    (row_email in {incoming_email, incoming_personal_email} or row_personal_email in {incoming_email, incoming_personal_email})
                    and row_type == self._normalized(separation_status)
                    and row_group == incoming_group
                    and row_position == incoming_position
                ):
                    return {
                        "success": True,
                        "employee_email": employee_email,
                        "location": location,
                        "already_exists": True,
                        "action": "already_exists",
                    }

            rd = roster_data or {}
            row_width = max(len(rows[0]), max(header.values()) + 1)
            new_row: list[Any] = [""] * row_width

            # Populate from roster snapshot first, then override with explicit args
            _roster_fields = [
                "employee_id", "position", "grade_level", "subject", "supplements",
                "talent", "background_eligibility", "date_approved", "license",
                "personal_email", "nine_cell", "status",
                "nti_culture", "nti_content", "mupd_culture", "mupd_content",
                "rt_boy_pd_content", "cc_1", "cc_2", "cc_3", "start_date",
            ]
            for field in _roster_fields:
                idx = header.get(field)
                if idx is not None:
                    new_row[idx] = str(rd.get(field, "") or "")

            # Required fields
            if "name" in header:
                new_row[header["name"]] = str(rd.get("employee_name", "") or employee_name or "")
            if "email" in header:
                new_row[header["email"]] = str(rd.get("employee_email", "") or "")
            if "personal_email" in header:
                new_row[header["personal_email"]] = str(rd.get("personal_email", "") or employee_email)

            # Explicit overrides
            if "group" in header:
                new_row[header["group"]] = str(rd.get("job_category", "") or job_category or "")
            if "location" in header:
                new_row[header["location"]] = location
            if "manager_email" in header:
                new_row[header["manager_email"]] = str(rd.get("manager_email", "") or manager_email or "")
            if "separation_type" in header:
                new_row[header["separation_type"]] = separation_status
            if "status" in header:
                new_row[header["status"]] = separation_status
            if "separation_date" in header:
                new_row[header["separation_date"]] = effective_date
            if "date_processed" in header:
                new_row[header["date_processed"]] = _today_iso()
            if "notes" in header and notes:
                existing_notes = str(rd.get("notes", "") or "")
                new_row[header["notes"]] = f"{existing_notes}; {notes}".lstrip("; ") if existing_notes else notes
            if "position" in header and job_title and not rd.get("position"):
                new_row[header["position"]] = job_title

            # Append at end: insert a new row after the last used row
            append_row = len(rows) + 1
            range_address = f"A{append_row}:{_column_letter(row_width - 1)}{append_row}"
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(sheet_name)}/range(address='{quote(range_address)}')",
                {"values": [new_row]},
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
            )

            return {
                "success": True,
                "employee_email": employee_email,
                "location": location,
                "action": "added",
                "row_number": append_row,
            }
        except Exception as exc:
            logger.exception("add_separation_record failed")
            return {
                "success": False,
                "employee_email": employee_email,
                "location": location,
                "error": str(exc),
            }

    async def find_separation_record(
        self,
        employee_email: str,
        *,
        location: str,
        status_change: str = "",
    ) -> dict[str, Any]:
        """Look up an existing separation record."""
        try:
            workbook = self._staff_roster_workbook(location)
            sheet_name = workbook.get("separations_sheet_name", "Separations")

            rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=sheet_name,
            )

            if not rows:
                return {"found": False, "employee_email": employee_email, "location": location}

            header = _header_map(rows[0], _ALL_ALIASES)
            email_lower = employee_email.strip().lower()
            status_lower = status_change.strip().lower()

            for index, row in enumerate(rows[1:], start=2):
                row_email = _cell(row, header.get("email")).lower()
                if row_email != email_lower:
                    continue
                if status_lower:
                    row_type = _cell(row, header.get("separation_type")).lower()
                    if row_type != status_lower:
                        continue
                return {
                    "found": True,
                    "row_id": str(index),
                    "employee_email": _cell(row, header.get("email")) or employee_email,
                    "employee_name": _cell(row, header.get("name")),
                    "location": location,
                    "job_category": _cell(row, header.get("group")),
                    "position": _cell(row, header.get("position")),
                    "separation_type": _cell(row, header.get("separation_type")),
                    "separation_date": _cell(row, header.get("separation_date")),
                    "date_processed": _cell(row, header.get("date_processed")),
                }
            return {"found": False, "employee_email": employee_email, "location": location}
        except Exception as exc:
            logger.exception("find_separation_record failed")
            return {
                "found": False,
                "employee_email": employee_email,
                "location": location,
                "error": str(exc),
            }
