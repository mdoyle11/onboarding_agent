"""Excel onboarding tracker operations."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from onboarding_agent.config import settings
from onboarding_agent.domain.formatting import format_date
from onboarding_agent.domain.identity import identity_key, normalize_identity_part
from onboarding_agent.integrations.workbook.client import WorkbookGraphClient
from onboarding_agent.integrations.workbook.helpers import (
    column_letter as _column_letter,
)
from onboarding_agent.integrations.workbook.helpers import (
    header_map as _header_map,
)
from onboarding_agent.integrations.workbook.helpers import (
    latest_active_stage as _latest_active_stage,
)
from onboarding_agent.integrations.workbook.helpers import (
    resolve_stage_name as _resolve_stage_name,
)
from onboarding_agent.integrations.workbook.helpers import (
    row_to_stages as _row_to_stages,
)
from onboarding_agent.integrations.workbook.helpers import (
    stage_column_map as _stage_column_map,
)
from onboarding_agent.integrations.workbook.helpers import (
    today_iso as _today,
)
from onboarding_agent.integrations.workbook.schema import (
    HEADER_ROW,
    TRACKER_OPTIONAL_ALIASES,
    TRACKER_REQUIRED_ALIASES,
)

logger = logging.getLogger(__name__)


class TrackerClient(WorkbookGraphClient):
    """Workbook-backed onboarding tracker operations."""

    _index_header_row = 1
    _tracker_columns: dict[str, int] = {}
    _stage_columns: dict[str, int] = {}
    _cache_identity_to_row_id: dict[str, str] = {}
    _cache_email_to_row_ids: dict[str, list[str]] = {}

    _normalize_identity_part = staticmethod(normalize_identity_part)
    _identity_key = staticmethod(identity_key)

    @staticmethod
    def _row_job_title(row: list[Any]) -> str:
        idx = TrackerClient._tracker_columns.get("job_title")
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "")

    @staticmethod
    def _row_status_change(row: list[Any]) -> str:
        idx = TrackerClient._tracker_columns.get("status_change")
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "")

    @classmethod
    def _rebuild_email_index(cls, header_row: int, rows: list[list[Any]]) -> None:
        if not rows:
            cls._index_header_row = header_row
            cls._tracker_columns = {}
            cls._stage_columns = {}
            cls._cache_identity_to_row_id = {}
            cls._cache_email_to_row_ids = {}
            return

        header = rows[0]
        tracker_aliases = {**TRACKER_REQUIRED_ALIASES, **TRACKER_OPTIONAL_ALIASES}
        tracker_columns = _header_map(header, tracker_aliases)
        missing = [key for key in TRACKER_REQUIRED_ALIASES if key not in tracker_columns]
        if missing:
            raise RuntimeError(f"Tracker table is missing required headers: {', '.join(missing)}")

        stage_columns = _stage_column_map(header)
        identity_index: dict[str, str] = {}
        email_index: dict[str, list[str]] = {}
        for row_number, row in enumerate(rows[1:], start=header_row + 1):
            email_idx = tracker_columns["staff_email"]
            if len(row) <= email_idx:
                continue
            email = str(row[email_idx] or "").strip().lower()
            if email:
                row_id = str(row_number)
                location_idx = tracker_columns.get("work_location")
                location = str(row[location_idx]) if location_idx is not None and len(row) > location_idx else ""
                job_title = cls._row_job_title(row)
                status_change = cls._row_status_change(row)
                identity_index[cls._identity_key(email, location, job_title, status_change)] = row_id
                email_index.setdefault(email, []).append(row_id)
        cls._index_header_row = header_row
        cls._tracker_columns = tracker_columns
        cls._stage_columns = stage_columns
        cls._cache_identity_to_row_id = identity_index
        cls._cache_email_to_row_ids = email_index

    @classmethod
    def _clear_index(cls) -> None:
        cls._index_header_row = 1
        cls._tracker_columns = {}
        cls._stage_columns = {}
        cls._cache_identity_to_row_id = {}
        cls._cache_email_to_row_ids = {}

    async def _refresh_index(self) -> tuple[int, list[list[Any]]]:
        header_row, rows = await self._tracker_rows_with_start_row()
        self._rebuild_email_index(header_row, rows)
        return header_row, rows

    async def _get_row_by_row_id(self, row_id: str) -> list[Any] | None:
        try:
            row_number = int(row_id)
        except ValueError:
            return None

        range_address = quote(f"A{row_number}:P{row_number}")
        data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(settings.graph_excel_sheet_name)}/range(address='{range_address}')",
        )
        values = data.get("values", []) if isinstance(data, dict) else []
        if not values:
            return None
        first_row = values[0]
        if not isinstance(first_row, list):
            return None
        return first_row

    @staticmethod
    def _row_matches_identity(
        row: list[Any],
        employee_email: str,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> bool:
        email_idx = TrackerClient._tracker_columns.get("staff_email")
        if email_idx is None or len(row) <= email_idx:
            return False
        row_email = str(row[email_idx] or "").strip().lower()
        if row_email != employee_email.strip().lower():
            return False
        if location:
            location_idx = TrackerClient._tracker_columns.get("work_location")
            row_location = (
                str(row[location_idx] or "").strip().lower()
                if location_idx is not None and len(row) > location_idx else ""
            )
            if row_location != location.strip().lower():
                return False
        if job_title:
            row_job_title = str(TrackerClient._row_job_title(row) or "").strip().lower()
            if row_job_title != job_title.strip().lower():
                return False
        if status_change:
            row_status_change = str(TrackerClient._row_status_change(row) or "").strip().lower()
            if row_status_change != status_change.strip().lower():
                return False
        return True

    @staticmethod
    def _employee_payload(row: list[Any], row_id: str) -> dict[str, Any]:
        stages = _row_to_stages(row, TrackerClient._stage_columns)
        location_idx = TrackerClient._tracker_columns.get("work_location")
        name_idx = TrackerClient._tracker_columns.get("staff_name")
        email_idx = TrackerClient._tracker_columns.get("staff_email")
        start_date_idx = TrackerClient._tracker_columns.get("requested_start_date")
        manager_idx = TrackerClient._tracker_columns.get("requesting_manager")
        location = str(row[location_idx]) if location_idx is not None and len(row) > location_idx else ""
        job_title = TrackerClient._row_job_title(row)
        status_change = TrackerClient._row_status_change(row)
        email = str(row[email_idx]) if email_idx is not None and len(row) > email_idx else ""
        return {
            "found": True,
            "row_id": row_id,
            "name": str(row[name_idx]) if name_idx is not None and len(row) > name_idx else "",
            "email": email,
            "location": location,
            "start_date": str(row[start_date_idx]) if start_date_idx is not None and len(row) > start_date_idx else "",
            "job_title": job_title,
            "status_change": status_change,
            "position": job_title,
            "manager_email": str(row[manager_idx]) if manager_idx is not None and len(row) > manager_idx else "",
            "identity_key": TrackerClient._identity_key(email, location, job_title, status_change),
            "stages": stages,
            "status": _latest_active_stage(stages),
        }

    @staticmethod
    def _match_payload(row: list[Any], row_id: str) -> dict[str, str]:
        added_to_tracker_idx = TrackerClient._stage_columns.get("Added to Tracker")
        email_idx = TrackerClient._tracker_columns.get("staff_email")
        location_idx = TrackerClient._tracker_columns.get("work_location")
        return {
            "row_id": row_id,
            "email": str(row[email_idx]) if email_idx is not None and len(row) > email_idx else "",
            "location": str(row[location_idx]) if location_idx is not None and len(row) > location_idx else "",
            "job_title": TrackerClient._row_job_title(row),
            "status_change": TrackerClient._row_status_change(row),
            "added_to_tracker": format_date(
                str(row[added_to_tracker_idx]) if added_to_tracker_idx is not None and len(row) > added_to_tracker_idx else ""
            ),
        }

    async def find_employee_in_tracker(
        self,
        employee_email: str,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        try:
            email_key = employee_email.strip().lower()
            location_key = location.strip()
            job_title_key = job_title.strip()
            status_change_key = status_change.strip()
            requested_identity = self._identity_key(email_key, location_key, job_title_key, status_change_key)

            candidate_row_ids: list[str] = []
            if location_key or job_title_key or status_change_key:
                exact_row_id = self._cache_identity_to_row_id.get(requested_identity, "")
                if exact_row_id:
                    candidate_row_ids = [exact_row_id]
            else:
                candidate_row_ids = list(self._cache_email_to_row_ids.get(email_key, []))

            verified_matches: list[tuple[str, list[Any]]] = []
            for row_id in candidate_row_ids:
                row = await self._get_row_by_row_id(row_id)
                if row is not None and self._row_matches_identity(
                    row,
                    email_key,
                    location_key,
                    job_title_key,
                    status_change_key,
                ):
                    verified_matches.append((row_id, row))

            if len(verified_matches) == 1:
                return self._employee_payload(verified_matches[0][1], verified_matches[0][0])
            if len(verified_matches) > 1:
                return {
                    "found": False,
                    "row_id": "",
                    "stages": {},
                    "multiple_matches": True,
                    "error": (
                        "Multiple tracker rows match the provided identifier. "
                        "Pass location, job_title, and status_change to disambiguate."
                    ),
                    "matches": [self._match_payload(row, row_id) for row_id, row in verified_matches],
                }

            header_row_number, rows = await self._refresh_index()
            if not rows:
                return {"found": False, "row_id": "", "stages": {}}

            matches: list[tuple[str, list[Any]]] = []
            for i, scan_row in enumerate(rows[1:], start=header_row_number + 1):
                if self._row_matches_identity(
                    scan_row,
                    email_key,
                    location_key,
                    job_title_key,
                    status_change_key,
                ):
                    matches.append((str(i), scan_row))

            if not matches:
                return {"found": False, "row_id": "", "stages": {}}
            if len(matches) > 1:
                return {
                    "found": False,
                    "row_id": "",
                    "stages": {},
                    "multiple_matches": True,
                    "error": (
                        "Multiple tracker rows match the provided identifier. "
                        "Pass location, job_title, and status_change to disambiguate."
                    ),
                    "matches": [self._match_payload(row, row_id) for row_id, row in matches],
                }

            row_id, row = matches[0]
            identity_key = self._identity_key(
                email_key,
                str(row[self._tracker_columns["work_location"]]) if "work_location" in self._tracker_columns and len(row) > self._tracker_columns["work_location"] else "",
                self._row_job_title(row),
                self._row_status_change(row),
            )
            self._cache_identity_to_row_id[identity_key] = row_id
            self._cache_email_to_row_ids.setdefault(email_key, [])
            if row_id not in self._cache_email_to_row_ids[email_key]:
                self._cache_email_to_row_ids[email_key].append(row_id)
            return self._employee_payload(row, row_id)
        except Exception as exc:
            logger.exception("find_employee_in_tracker failed")
            return {"found": False, "row_id": "", "stages": {}, "error": str(exc)}

    async def add_employee_to_tracker(
        self,
        staff_name: str = "",
        staff_email: str = "",
        requested_start_date: str = "",
        job_title: str = "",
        work_location: str = "",
        requesting_manager: str = "",
        status_change: str = "",
        staff_phone: str = "",
        education_level: str = "",
        supplements: str = "",
        license_number: str = "",
        uploaded_credentials: str = "",
        compensation: str = "",
        employment_type: str = "",
        contract_term: str = "",
    ) -> dict[str, Any]:
        try:
            final_name = staff_name
            final_email = staff_email
            final_requested_start_date = requested_start_date
            final_job_title = job_title
            final_work_location = work_location
            final_requesting_manager = requesting_manager

            header_row_number, rows = await self._tracker_rows_with_start_row()
            next_row = (header_row_number + len(rows)) if rows else 2

            self._rebuild_email_index(header_row_number, rows)
            row = [""] * (len(rows[0]) if rows else len(HEADER_ROW))
            name_idx = self._tracker_columns.get("staff_name")
            email_idx = self._tracker_columns.get("staff_email")
            location_idx = self._tracker_columns.get("work_location")
            start_idx = self._tracker_columns.get("requested_start_date")
            manager_idx = self._tracker_columns.get("requesting_manager")
            job_idx = self._tracker_columns.get("job_title")
            status_change_idx = self._tracker_columns.get("status_change")
            staff_phone_idx = self._tracker_columns.get("staff_phone")
            education_level_idx = self._tracker_columns.get("education_level")
            supplements_idx = self._tracker_columns.get("supplements")
            license_idx = self._tracker_columns.get("license_number")
            uploaded_credentials_idx = self._tracker_columns.get("uploaded_credentials")
            compensation_idx = self._tracker_columns.get("compensation")
            employment_type_idx = self._tracker_columns.get("employment_type")
            contract_term_idx = self._tracker_columns.get("contract_term")
            added_idx = self._stage_columns.get("Added to Tracker")

            if name_idx is not None:
                row[name_idx] = final_name
            if email_idx is not None:
                row[email_idx] = final_email
            if location_idx is not None:
                row[location_idx] = final_work_location
            if start_idx is not None:
                row[start_idx] = final_requested_start_date
            if manager_idx is not None:
                row[manager_idx] = final_requesting_manager
            if job_idx is not None:
                row[job_idx] = final_job_title
            if status_change_idx is not None:
                row[status_change_idx] = status_change
            if staff_phone_idx is not None:
                row[staff_phone_idx] = staff_phone
            if education_level_idx is not None:
                row[education_level_idx] = education_level
            if supplements_idx is not None:
                row[supplements_idx] = supplements
            if license_idx is not None:
                row[license_idx] = license_number
            if uploaded_credentials_idx is not None:
                row[uploaded_credentials_idx] = uploaded_credentials
            if compensation_idx is not None:
                row[compensation_idx] = compensation
            if employment_type_idx is not None:
                row[employment_type_idx] = employment_type
            if contract_term_idx is not None:
                row[contract_term_idx] = contract_term
            if added_idx is not None:
                row[added_idx] = _today()

            logger.info("Writing Excel row %s with direct mapping values=%s", next_row, row)

            table_name = settings.graph_excel_table_name.strip()
            if table_name:
                await self._graph_workbook_request(
                    "POST",
                    f"/tables/{quote(table_name)}/rows/add",
                    {"values": [row]},
                )
            else:
                range_address = quote(f"A{next_row}:P{next_row}")
                await self._graph_workbook_request(
                    "PATCH",
                    f"/worksheets/{quote(settings.graph_excel_sheet_name)}/range(address='{range_address}')",
                    {"values": [row]},
                )

            found = await self.find_employee_in_tracker(
                final_email,
                location=final_work_location,
                job_title=final_job_title,
                status_change=status_change,
            )
            row_id = str(found.get("row_id", "") or next_row)
            if found.get("found"):
                identity_key = str(found.get("identity_key", "") or "")
                if identity_key:
                    self._cache_identity_to_row_id[identity_key] = row_id
                email_key = final_email.strip().lower()
                self._cache_email_to_row_ids.setdefault(email_key, [])
                if row_id not in self._cache_email_to_row_ids[email_key]:
                    self._cache_email_to_row_ids[email_key].append(row_id)
            return {"success": True, "row_id": row_id}
        except Exception as exc:
            logger.exception("add_employee_to_tracker failed")
            self._clear_index()
            return {"success": False, "row_id": "", "error": str(exc)}

    async def update_stage(
        self,
        employee_email: str,
        stage_name: str,
        value: str | None = None,
        *,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        if not self._stage_columns:
            await self._refresh_index()
        resolved_stage_name = _resolve_stage_name(stage_name, self._stage_columns)
        if resolved_stage_name is None:
            await self._refresh_index()
            resolved_stage_name = _resolve_stage_name(stage_name, self._stage_columns)
        if resolved_stage_name is None:
            return {
                "success": False,
                "error": f"Unknown stage '{stage_name}'. Valid stages: {list(self._stage_columns)}",
            }

        employee = await self.find_employee_in_tracker(
            employee_email,
            location=location,
            job_title=job_title,
            status_change=status_change,
        )
        if not employee.get("found"):
            return {"success": False, "error": f"Employee {employee_email} not found in tracker"}

        try:
            row_id = employee["row_id"]
            stage_idx = self._stage_columns[resolved_stage_name]
            col_letter = _column_letter(stage_idx)
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
        stage_name = _resolve_stage_name(new_status, self._stage_columns) or "Added to Tracker"
        row = await self._get_row_by_row_id(row_id)
        if row is None:
            return {"success": False, "row_id": row_id, "error": "Row not found"}
        email_idx = self._tracker_columns.get("staff_email")
        employee_email = str(row[email_idx]) if email_idx is not None and len(row) > email_idx else ""
        if not employee_email:
            return {"success": False, "row_id": row_id, "error": "Email not found for row"}
        result = await self.update_stage(employee_email, stage_name)
        return {"row_id": row_id, **result}

    async def list_all_employees(self) -> dict[str, Any]:
        try:
            header_row_number, rows = await self._tracker_rows_with_start_row()
            self._rebuild_email_index(header_row_number, rows)
            employees = []
            name_idx = self._tracker_columns.get("staff_name")
            email_idx = self._tracker_columns.get("staff_email")
            location_idx = self._tracker_columns.get("work_location")
            start_idx = self._tracker_columns.get("requested_start_date")
            for row in rows[1:]:
                if email_idx is None or len(row) <= email_idx or not row[email_idx]:
                    continue
                employees.append(
                    {
                        "name": str(row[name_idx]) if name_idx is not None and len(row) > name_idx else "",
                        "email": str(row[email_idx]),
                        "location": str(row[location_idx]) if location_idx is not None and len(row) > location_idx else "",
                        "start_date": str(row[start_idx]) if start_idx is not None and len(row) > start_idx else "",
                        "job_title": self._row_job_title(row),
                        "position": self._row_job_title(row),
                        "stages": _row_to_stages(row, self._stage_columns),
                    }
                )
            return {"success": True, "employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.exception("list_all_employees failed")
            return {"success": False, "employees": [], "count": 0, "error": str(exc)}

    async def get_employee_stages(
        self,
        employee_email: str,
        *,
        location: str = "",
        job_title: str = "",
        status_change: str = "",
    ) -> dict[str, Any]:
        result = await self.find_employee_in_tracker(
            employee_email,
            location=location,
            job_title=job_title,
            status_change=status_change,
        )
        if not result.get("found"):
            return {
                "found": False,
                "employee_email": employee_email,
                "stages": {},
                "multiple_matches": bool(result.get("multiple_matches", False)),
                "matches": result.get("matches", []),
                "error": result.get("error", ""),
            }
        return {
            "found": True,
            "employee_email": employee_email,
            "name": result.get("name", ""),
            "start_date": result.get("start_date", ""),
            "status_change": result.get("status_change", ""),
            "stages": result.get("stages", {}),
        }
