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

    @staticmethod
    def _group_match_key(value: str) -> str:
        normalized = " ".join(str(value or "").strip().lower().split())
        if not normalized:
            return ""
        words: list[str] = []
        for word in normalized.split(" "):
            if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
                words.append(word[:-1])
            else:
                words.append(word)
        return " ".join(words)

    @classmethod
    def _resolve_group_value(
        cls,
        rows: list[list[Any]],
        header: dict[str, int],
        requested_group: str,
    ) -> str:
        requested = str(requested_group or "").strip()
        if not requested:
            return ""

        exact_lower = requested.lower()
        requested_key = cls._group_match_key(requested)
        resolved_by_key = ""

        for row in rows[1:]:
            candidate = _cell(row, header.get("group")).strip()
            if not candidate:
                continue
            if candidate.lower() == exact_lower:
                return candidate
            if not resolved_by_key and cls._group_match_key(candidate) == requested_key:
                resolved_by_key = candidate

        return resolved_by_key or requested

    @staticmethod
    def _is_totals_row(row: list[Any], roster_header: dict[str, int]) -> bool:
        return _cell(row, roster_header.get("name")).strip().lower() == "totals"

    @staticmethod
    def _row_range_address(row_number: int, row_width: int) -> str:
        return f"A{row_number}:{_column_letter(row_width - 1)}{row_number}"

    @staticmethod
    def _row_width(roster_rows: list[list[Any]], roster_header: dict[str, int]) -> int:
        return max(len(roster_rows[0]), max(roster_header.values()) + 1)

    @classmethod
    def _find_group_insert_row(
        cls,
        roster_rows: list[list[Any]],
        roster_header: dict[str, int],
        *,
        job_category: str,
    ) -> int | None:
        normalized_group = job_category.strip().lower()
        last_group_row: int | None = None
        for row_number, row in enumerate(roster_rows[1:], start=2):
            if _cell(row, roster_header.get("group")).lower() != normalized_group:
                continue
            if cls._is_totals_row(row, roster_header):
                return row_number
            last_group_row = row_number
        if last_group_row is not None:
            return last_group_row + 1
        return None

    @staticmethod
    def _updated_roster_row(
        existing_row: list[Any],
        roster_header: dict[str, int],
        *,
        employee_id: str = "",
        employee_name: str = "",
        work_email: str = "",
        personal_email: str = "",
        position: str = "",
        job_category: str = "",
        grade_level: str = "",
        subject: str = "",
        supplements: str = "",
        talent: str = "",
        background_eligibility: str = "",
        date_approved: str = "",
        license_value: str = "",
        nine_cell: str = "",
        notes: str = "",
        roster_status: str = "",
        nti_culture: str = "",
        nti_content: str = "",
        mupd_culture: str = "",
        mupd_content: str = "",
        rt_boy_pd_content: str = "",
        cc_1: str = "",
        cc_2: str = "",
        cc_3: str = "",
        location: str = "",
    ) -> list[Any]:
        row = list(existing_row)

        def set_if_present(key: str, value: str) -> None:
            idx = roster_header.get(key)
            if idx is not None:
                while len(row) <= idx:
                    row.append("")
                row[idx] = value

        if employee_id:
            set_if_present("employee_id", employee_id)
        if employee_name:
            set_if_present("name", employee_name)
        if work_email:
            set_if_present("email", work_email)
        if personal_email:
            set_if_present("personal_email", personal_email)
        if position:
            set_if_present("position", position)
        if job_category:
            set_if_present("group", job_category)
        if grade_level:
            set_if_present("grade_level", grade_level)
        if subject:
            set_if_present("subject", subject)
        if supplements:
            set_if_present("supplements", supplements)
        if talent:
            set_if_present("talent", talent)
        if background_eligibility:
            set_if_present("background_eligibility", background_eligibility)
        if date_approved:
            set_if_present("date_approved", date_approved)
        if license_value:
            set_if_present("license", license_value)
        if nine_cell:
            set_if_present("nine_cell", nine_cell)
        if notes:
            set_if_present("notes", notes)
        if roster_status:
            set_if_present("status", roster_status)
        if nti_culture:
            set_if_present("nti_culture", nti_culture)
        if nti_content:
            set_if_present("nti_content", nti_content)
        if mupd_culture:
            set_if_present("mupd_culture", mupd_culture)
        if mupd_content:
            set_if_present("mupd_content", mupd_content)
        if rt_boy_pd_content:
            set_if_present("rt_boy_pd_content", rt_boy_pd_content)
        if cc_1:
            set_if_present("cc_1", cc_1)
        if cc_2:
            set_if_present("cc_2", cc_2)
        if cc_3:
            set_if_present("cc_3", cc_3)
        if location:
            set_if_present("location", location)
        return row

    @staticmethod
    def _row_matches_roster_identity(
        row: list[Any],
        roster_header: dict[str, int],
        *,
        employee_email: str,
        job_category: str,
        personal_email: str = "",
        employee_name: str = "",
        position: str = "",
        location: str = "",
    ) -> bool:
        row_email = _cell(row, roster_header.get("email")).lower()
        row_personal_email = _cell(row, roster_header.get("personal_email")).lower()
        row_name = _cell(row, roster_header.get("name")).lower()
        row_position = _cell(row, roster_header.get("position")).lower()
        personal_email_matches = bool(personal_email.strip()) and row_personal_email == personal_email.strip().lower()
        email_matches = bool(employee_email.strip()) and row_email == employee_email.strip().lower()
        name_position_matches = (
            bool(employee_name.strip())
            and bool(position.strip())
            and row_name == employee_name.strip().lower()
            and row_position == position.strip().lower()
        )
        if not (personal_email_matches or email_matches or name_position_matches):
            return False
        if _cell(row, roster_header.get("group")).lower() != job_category.strip().lower():
            return False
        location_idx = roster_header.get("location")
        return not (
            location and location_idx is not None and _cell(row, location_idx).lower() != location.strip().lower()
        )

    @classmethod
    def _row_matches_written_values(
        cls,
        row: list[Any],
        roster_header: dict[str, int],
        *,
        expected_row: list[Any],
        job_category: str,
        employee_email: str,
        location: str = "",
    ) -> bool:
        if cls._is_totals_row(row, roster_header):
            return False
        if _cell(row, roster_header.get("group")).lower() != job_category.strip().lower():
            return False

        name_idx = roster_header.get("name")
        email_idx = roster_header.get("email")
        personal_email_idx = roster_header.get("personal_email")
        position_idx = roster_header.get("position")
        location_idx = roster_header.get("location")

        def expected(idx: int | None) -> str:
            return str(expected_row[idx]).strip().lower() if idx is not None and len(expected_row) > idx else ""

        if name_idx is not None and expected(name_idx) and _cell(row, name_idx).lower() != expected(name_idx):
            return False
        if position_idx is not None and expected(position_idx) and _cell(row, position_idx).lower() != expected(position_idx):
            return False
        if personal_email_idx is not None and expected(personal_email_idx):
            return _cell(row, personal_email_idx).lower() == expected(personal_email_idx)
        if email_idx is not None and expected(email_idx):
            return _cell(row, email_idx).lower() == expected(email_idx)
        return not (
            location_idx is not None and location and _cell(row, location_idx).lower() != location.strip().lower()
        ) and bool(employee_email.strip())

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

            resolved_category = self._resolve_group_value(capacity_rows, capacity_header, job_category)
            normalized_category = resolved_category.strip().lower()
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
                    "job_category": resolved_category or job_category,
                    "error": f"No capacity row found for category '{job_category}'",
                }

            current_count = 0
            for row in roster_rows[1:]:
                if self._is_totals_row(row, roster_header):
                    continue
                email = _cell(row, roster_header.get("email"))
                group = _cell(row, roster_header.get("group"))
                if not email or not group:
                    continue
                if group.lower() == normalized_category:
                    current_count += 1

            return {
                "success": True,
                "location": location,
                "job_category": resolved_category or job_category,
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

    async def _insert_roster_row(
        self,
        *,
        drive_id: str,
        item_id: str,
        sheet_name: str,
        row_number: int,
        row_width: int,
    ) -> None:
        range_address = quote(self._row_range_address(row_number, row_width))
        await self._graph_workbook_request(
            "POST",
            f"/worksheets/{quote(sheet_name)}/range(address='{range_address}')/insert",
            {"shift": "Down"},
            drive_id=drive_id,
            item_id=item_id,
        )

    async def _delete_roster_row(
        self,
        *,
        drive_id: str,
        item_id: str,
        sheet_name: str,
        row_number: int,
        row_width: int,
    ) -> None:
        range_address = quote(self._row_range_address(row_number, row_width))
        await self._graph_workbook_request(
            "POST",
            f"/worksheets/{quote(sheet_name)}/range(address='{range_address}')/delete",
            {"shift": "Up"},
            drive_id=drive_id,
            item_id=item_id,
        )

    async def find_employee_in_staff_roster(
        self,
        employee_email: str,
        *,
        location: str,
        job_category: str = "",
        personal_email: str = "",
        employee_name: str = "",
        position: str = "",
    ) -> dict[str, Any]:
        try:
            workbook = self._staff_roster_workbook(location)
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not roster_rows:
                return {"found": False, "employee_email": employee_email, "location": location, "error": "Roster sheet is empty"}

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            resolved_job_category = self._resolve_group_value(roster_rows, roster_header, job_category)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {
                    "found": False,
                    "employee_email": employee_email,
                    "location": location,
                    "error": f"Roster sheet is missing required columns: {missing_list}",
                }

            matches: list[dict[str, Any]] = []
            for index, row in enumerate(roster_rows[1:], start=2):
                row_email = _cell(row, roster_header.get("email"))
                row_personal_email = _cell(row, roster_header.get("personal_email"))
                found_group = _cell(row, roster_header.get("group"))
                found_name = _cell(row, roster_header.get("name"))
                found_position = _cell(row, roster_header.get("position"))
                personal_email_matches = row_personal_email.lower() == personal_email.strip().lower() if personal_email.strip() else False
                email_matches = row_email.lower() == employee_email.strip().lower()
                name_position_matches = (
                    bool(employee_name.strip())
                    and bool(position.strip())
                    and found_name.lower() == employee_name.strip().lower()
                    and found_position.lower() == position.strip().lower()
                )
                if not (personal_email_matches or email_matches or name_position_matches):
                    continue
                if resolved_job_category and found_group.lower() != resolved_job_category.strip().lower():
                    continue
                matches.append(
                    {
                        "row_id": str(index),
                        "employee_id": _cell(row, roster_header.get("employee_id")),
                        "employee_email": row_email or employee_email,
                        "personal_email": row_personal_email or personal_email,
                        "location": location,
                        "employee_name": found_name,
                        "job_category": found_group,
                        "position": found_position,
                        "grade_level": _cell(row, roster_header.get("grade_level")),
                        "subject": _cell(row, roster_header.get("subject")),
                        "supplements": _cell(row, roster_header.get("supplements")),
                        "talent": _cell(row, roster_header.get("talent")),
                        "background_eligibility": _cell(row, roster_header.get("background_eligibility")),
                        "date_approved": _cell(row, roster_header.get("date_approved")),
                        "license": _cell(row, roster_header.get("license")),
                        "nine_cell": _cell(row, roster_header.get("nine_cell")),
                        "notes": _cell(row, roster_header.get("notes")),
                        "status": _cell(row, roster_header.get("status")),
                        "nti_culture": _cell(row, roster_header.get("nti_culture")),
                        "nti_content": _cell(row, roster_header.get("nti_content")),
                        "mupd_culture": _cell(row, roster_header.get("mupd_culture")),
                        "mupd_content": _cell(row, roster_header.get("mupd_content")),
                        "rt_boy_pd_content": _cell(row, roster_header.get("rt_boy_pd_content")),
                        "cc_1": _cell(row, roster_header.get("cc_1")),
                        "cc_2": _cell(row, roster_header.get("cc_2")),
                        "cc_3": _cell(row, roster_header.get("cc_3")),
                    }
                )

            if not matches:
                return {"found": False, "employee_email": employee_email, "location": location}
            if len(matches) > 1:
                return {
                    "found": False,
                    "employee_email": employee_email,
                    "location": location,
                    "multiple_matches": True,
                    "matches": matches,
                    "error": "Multiple staff roster rows matched this employee.",
                }
            return {"found": True, **matches[0]}
        except Exception as exc:
            logger.exception("find_employee_in_staff_roster failed")
            return {
                "found": False,
                "employee_email": employee_email,
                "location": location,
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
        submission_id: str = "",
    ) -> dict[str, Any]:
        try:
            employee = await TrackerClient().resolve_employee_relaxed(
                employee_email,
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
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
            resolved_job_category = self._resolve_group_value(roster_rows, roster_header, job_category)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {"success": False, "error": f"Roster sheet is missing required columns: {missing_list}"}

            insert_row = self._find_group_insert_row(roster_rows, roster_header, job_category=resolved_job_category)
            if insert_row is None:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": resolved_job_category or job_category,
                    "location": location,
                    "error": f"No roster section found for group '{job_category}'",
                }

            for index, row in enumerate(roster_rows[1:], start=2):
                if self._row_matches_roster_identity(
                    row,
                    roster_header,
                    employee_email=employee_email,
                    job_category=resolved_job_category,
                    personal_email=employee_email,
                    employee_name=str(employee.get("name", "") or ""),
                    position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
                    location=location,
                ):
                    return {
                        "success": True,
                        "employee_email": employee_email,
                        "job_category": resolved_job_category or job_category,
                        "location": location,
                        "row_id": str(index),
                        "already_exists": True,
                    }

            capacity = await self.check_staff_roster_capacity(location, resolved_job_category or job_category)
            if not capacity.get("success"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": resolved_job_category or job_category,
                    "location": location,
                    "error": str(capacity.get("error", "Capacity check failed")),
                }
            if not capacity.get("has_capacity"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": resolved_job_category or job_category,
                    "location": location,
                    "current_count": capacity.get("current_count", 0),
                    "max_capacity": capacity.get("max_capacity", 0),
                    "error": f"Category '{job_category}' at {location} is at capacity",
                }

            row_width = max(len(roster_rows[0]), max(roster_header.values()) + 1)
            new_row = [""] * row_width
            new_row[roster_header["name"]] = str(employee.get("name", "") or "")
            new_row[roster_header["email"]] = employee_email
            new_row[roster_header["group"]] = resolved_job_category or job_category

            optional_values = {
                "start_date": str(employee.get("start_date", "") or ""),
                "position": str(employee.get("position", "") or employee.get("job_title", "") or ""),
                "personal_email": employee_email,
                "manager_email": str(employee.get("manager_email", "") or ""),
                "location": location,
            }
            for key, value in optional_values.items():
                idx = roster_header.get(key)
                if idx is not None:
                    new_row[idx] = value

            logger.info(
                "Writing staff roster row %s for %s/%s values=%s",
                insert_row,
                location,
                resolved_job_category or job_category,
                new_row,
            )
            await self._insert_roster_row(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
                row_number=insert_row,
                row_width=len(new_row),
            )
            range_address = quote(self._row_range_address(insert_row, len(new_row)))
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(workbook['roster_sheet_name'])}/range(address='{range_address}')",
                {"values": [new_row]},
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
            )

            refreshed_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not refreshed_rows:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "job_category": job_category,
                    "location": location,
                    "error": "Roster verification failed after write",
                }

            refreshed_header = _header_map(refreshed_rows[0], roster_aliases)
            if len(refreshed_rows) >= insert_row + 1:
                inserted_row = refreshed_rows[insert_row - 1]
                if self._row_matches_written_values(
                    inserted_row,
                    refreshed_header,
                    expected_row=new_row,
                    job_category=resolved_job_category or job_category,
                    employee_email=employee_email,
                    location=location,
                ):
                    return {
                        "success": True,
                        "employee_email": employee_email,
                        "job_category": resolved_job_category or job_category,
                        "location": location,
                        "row_id": str(insert_row),
                        "already_exists": False,
                        "remaining_capacity": int(capacity.get("remaining_capacity", 0)) - 1,
                    }
            for index, row in enumerate(refreshed_rows[1:], start=2):
                if self._row_matches_roster_identity(
                    row,
                    refreshed_header,
                    employee_email=employee_email,
                    job_category=resolved_job_category or job_category,
                    personal_email=employee_email,
                    employee_name=str(employee.get("name", "") or ""),
                    position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
                    location=location,
                ):
                    return {
                        "success": True,
                        "employee_email": employee_email,
                        "job_category": resolved_job_category or job_category,
                        "location": location,
                        "row_id": str(index),
                        "already_exists": False,
                        "remaining_capacity": int(capacity.get("remaining_capacity", 0)) - 1,
                    }

            return {
                "success": False,
                "employee_email": employee_email,
                "job_category": resolved_job_category or job_category,
                "location": location,
                "error": (
                    f"Roster write for {employee_email} at {location} in group '{job_category}' "
                    "did not verify after the workbook update."
                ),
            }
        except Exception as exc:
            logger.exception("add_employee_to_staff_roster failed")
            return {
                "success": False,
                "employee_email": employee_email,
                "job_category": job_category,
                "error": str(exc),
            }

    async def remove_employee_from_staff_roster(
        self,
        employee_email: str,
        *,
        location: str,
        job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        try:
            employee = await TrackerClient().resolve_employee_relaxed(
                employee_email,
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            if not employee.get("found"):
                matches = employee.get("matches", [])
                if employee.get("multiple_matches") and isinstance(matches, list) and matches:
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "location": location,
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
                    "location": location,
                    "error": f"Employee {employee_email} not found in onboarding tracker",
                }

            workbook = self._staff_roster_workbook(location)
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not roster_rows:
                return {"success": False, "employee_email": employee_email, "location": location, "error": "Roster sheet is empty"}

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {"success": False, "error": f"Roster sheet is missing required columns: {missing_list}"}

            match = await self.find_employee_in_staff_roster(
                employee_email,
                location=location,
                job_category=job_category,
                personal_email=employee_email,
                employee_name=str(employee.get("name", "") or ""),
                position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
            )
            if not match.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "job_category": job_category,
                    "error": str(match.get("error", f"{employee_email} is not in the staff roster")),
                }

            row_id = int(str(match.get("row_id", "0") or "0"))
            if row_id <= 1:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "job_category": job_category,
                    "error": "Resolved roster row is invalid",
                }

            row_width = max(len(roster_rows[0]), max(roster_header.values()) + 1)
            await self._delete_roster_row(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
                row_number=row_id,
                row_width=row_width,
            )

            refreshed = await self.find_employee_in_staff_roster(
                employee_email,
                location=location,
                job_category=job_category or str(match.get("job_category", "") or ""),
                personal_email=employee_email,
                employee_name=str(employee.get("name", "") or ""),
                position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
            )
            if refreshed.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "job_category": job_category or str(match.get("job_category", "") or ""),
                    "error": "Roster delete did not verify after the workbook update.",
                }

            return {
                "success": True,
                "employee_email": employee_email,
                "location": location,
                "job_category": job_category or str(match.get("job_category", "") or ""),
                "row_id": str(row_id),
            }
        except Exception as exc:
            logger.exception("remove_employee_from_staff_roster failed")
            return {
                "success": False,
                "employee_email": employee_email,
                "location": location,
                "job_category": job_category,
                "error": str(exc),
            }

    async def update_employee_leave_status(
        self,
        employee_email: str,
        *,
        location: str,
        status: str,
        note: str = "",
        job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Update the status and notes columns on an existing roster row."""
        try:
            employee = await TrackerClient().resolve_employee_relaxed(
                employee_email,
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )

            workbook = self._staff_roster_workbook(location)
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not roster_rows:
                return {"success": False, "employee_email": employee_email, "location": location, "error": "Roster sheet is empty"}

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)

            match = await self.find_employee_in_staff_roster(
                employee_email,
                location=location,
                job_category=job_category,
                personal_email=employee_email,
                employee_name=str(employee.get("name", "") or "") if employee.get("found") else "",
                position=str(employee.get("position", "") or employee.get("job_title", "") or "") if employee.get("found") else "",
            )
            if not match.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "error": str(match.get("error", f"{employee_email} is not in the staff roster")),
                }

            row_id = int(str(match.get("row_id", "0") or "0"))
            if row_id <= 1:
                return {"success": False, "employee_email": employee_email, "location": location, "error": "Resolved roster row is invalid"}

            current_row = list(roster_rows[row_id - 1])
            row_width = max(len(roster_rows[0]), max(roster_header.values()) + 1)
            while len(current_row) < row_width:
                current_row.append("")

            if "status" in roster_header:
                current_row[roster_header["status"]] = status
            if "notes" in roster_header and note:
                existing = str(current_row[roster_header["notes"]] or "").strip()
                current_row[roster_header["notes"]] = f"{existing}; {note}".lstrip("; ") if existing else note

            range_address = f"A{row_id}:{_column_letter(row_width - 1)}{row_id}"
            await self._graph_workbook_request(
                "PATCH",
                f"/worksheets/{quote(workbook['roster_sheet_name'])}/range(address='{quote(range_address)}')",
                {"values": [current_row]},
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
            )

            return {
                "success": True,
                "employee_email": employee_email,
                "location": location,
                "status": status,
                "employee_name": str(match.get("employee_name", "") or ""),
            }
        except Exception as exc:
            logger.exception("update_employee_leave_status failed")
            return {"success": False, "employee_email": employee_email, "location": location, "error": str(exc)}

    async def update_employee_in_staff_roster(
        self,
        employee_email: str,
        *,
        location: str,
        current_job_category: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
        employee_id: str = "",
        job_category: str = "",
        position: str = "",
        work_email: str = "",
        personal_email: str = "",
        employee_name: str = "",
        grade_level: str = "",
        subject: str = "",
        supplements: str = "",
        talent: str = "",
        background_eligibility: str = "",
        date_approved: str = "",
        license_value: str = "",
        nine_cell: str = "",
        notes: str = "",
        roster_status: str = "",
        nti_culture: str = "",
        nti_content: str = "",
        mupd_culture: str = "",
        mupd_content: str = "",
        rt_boy_pd_content: str = "",
        cc_1: str = "",
        cc_2: str = "",
        cc_3: str = "",
    ) -> dict[str, Any]:
        try:
            employee = await TrackerClient().resolve_employee_relaxed(
                employee_email,
                location=location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            if not employee.get("found"):
                matches = employee.get("matches", [])
                if employee.get("multiple_matches") and isinstance(matches, list) and matches:
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "location": location,
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
                    "location": location,
                    "error": f"Employee {employee_email} not found in onboarding tracker",
                }

            workbook = self._staff_roster_workbook(location)
            roster_rows = await self._used_range_rows(
                drive_id=workbook["drive_id"],
                item_id=workbook["item_id"],
                sheet_name=workbook["roster_sheet_name"],
            )
            if not roster_rows:
                return {"success": False, "employee_email": employee_email, "location": location, "error": "Roster sheet is empty"}

            roster_aliases = {**ROSTER_REQUIRED_ALIASES, **ROSTER_OPTIONAL_ALIASES}
            roster_header = _header_map(roster_rows[0], roster_aliases)
            missing = [key for key in ROSTER_REQUIRED_ALIASES if key not in roster_header]
            if missing:
                missing_list = ", ".join(missing)
                return {"success": False, "error": f"Roster sheet is missing required columns: {missing_list}"}

            match = await self.find_employee_in_staff_roster(
                employee_email,
                location=location,
                job_category=current_job_category,
                personal_email=employee_email,
                employee_name=str(employee.get("name", "") or ""),
                position=str(employee.get("position", "") or employee.get("job_title", "") or ""),
            )
            if not match.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "job_category": current_job_category,
                    "error": str(match.get("error", f"{employee_email} is not in the staff roster")),
                }

            row_id = int(str(match.get("row_id", "0") or "0"))
            if row_id <= 1:
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "error": "Resolved roster row is invalid",
                }

            current_row = list(roster_rows[row_id - 1])
            resolved_group = str(job_category or match.get("job_category", "") or "").strip()
            updated_row = self._updated_roster_row(
                current_row,
                roster_header,
                employee_id=employee_id,
                employee_name=employee_name or str(employee.get("name", "") or ""),
                work_email=work_email or _cell(current_row, roster_header.get("email")),
                personal_email=personal_email or employee_email,
                position=position or str(employee.get("position", "") or employee.get("job_title", "") or ""),
                job_category=resolved_group,
                grade_level=grade_level,
                subject=subject,
                supplements=supplements,
                talent=talent,
                background_eligibility=background_eligibility,
                date_approved=date_approved,
                license_value=license_value,
                nine_cell=nine_cell,
                notes=notes,
                roster_status=roster_status,
                nti_culture=nti_culture,
                nti_content=nti_content,
                mupd_culture=mupd_culture,
                mupd_content=mupd_content,
                rt_boy_pd_content=rt_boy_pd_content,
                cc_1=cc_1,
                cc_2=cc_2,
                cc_3=cc_3,
                location=location,
            )

            row_width = self._row_width(roster_rows, roster_header)
            current_group = str(match.get("job_category", "") or "").strip()
            moving_groups = bool(resolved_group) and resolved_group.lower() != current_group.lower()
            if moving_groups:
                capacity = await self.check_staff_roster_capacity(location, resolved_group)
                if not capacity.get("success"):
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "location": location,
                        "job_category": resolved_group,
                        "error": str(capacity.get("error", "Capacity check failed")),
                    }
                if not capacity.get("has_capacity"):
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "location": location,
                        "job_category": resolved_group,
                        "current_count": capacity.get("current_count", 0),
                        "max_capacity": capacity.get("max_capacity", 0),
                        "error": f"Category '{resolved_group}' at {location} is at capacity",
                    }

                refreshed_rows = await self._used_range_rows(
                    drive_id=workbook["drive_id"],
                    item_id=workbook["item_id"],
                    sheet_name=workbook["roster_sheet_name"],
                )
                refreshed_header = _header_map(refreshed_rows[0], roster_aliases)
                insert_row = self._find_group_insert_row(refreshed_rows, refreshed_header, job_category=resolved_group)
                if insert_row is None:
                    return {
                        "success": False,
                        "employee_email": employee_email,
                        "location": location,
                        "job_category": resolved_group,
                        "error": f"No roster section found for group '{resolved_group}'",
                    }
                await self._insert_roster_row(
                    drive_id=workbook["drive_id"],
                    item_id=workbook["item_id"],
                    sheet_name=workbook["roster_sheet_name"],
                    row_number=insert_row,
                    row_width=row_width,
                )
                insert_range = quote(self._row_range_address(insert_row, row_width))
                await self._graph_workbook_request(
                    "PATCH",
                    f"/worksheets/{quote(workbook['roster_sheet_name'])}/range(address='{insert_range}')",
                    {"values": [updated_row]},
                    drive_id=workbook["drive_id"],
                    item_id=workbook["item_id"],
                )

                delete_row = row_id + 1 if insert_row <= row_id else row_id
                await self._delete_roster_row(
                    drive_id=workbook["drive_id"],
                    item_id=workbook["item_id"],
                    sheet_name=workbook["roster_sheet_name"],
                    row_number=delete_row,
                    row_width=row_width,
                )
            else:
                range_address = quote(self._row_range_address(row_id, row_width))
                await self._graph_workbook_request(
                    "PATCH",
                    f"/worksheets/{quote(workbook['roster_sheet_name'])}/range(address='{range_address}')",
                    {"values": [updated_row]},
                    drive_id=workbook["drive_id"],
                    item_id=workbook["item_id"],
                )

            verified = await self.find_employee_in_staff_roster(
                work_email or employee_email,
                location=location,
                job_category=resolved_group or current_group,
                personal_email=personal_email or employee_email,
                employee_name=employee_name or str(employee.get("name", "") or ""),
                position=position or str(employee.get("position", "") or employee.get("job_title", "") or ""),
            )
            if not verified.get("found"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "location": location,
                    "job_category": resolved_group or current_group,
                    "error": "Roster update did not verify after the workbook update.",
                }

            return {
                "success": True,
                "employee_email": employee_email,
                "location": location,
                "job_category": resolved_group or current_group,
                "row_id": str(verified.get("row_id", "")),
            }
        except Exception as exc:
            logger.exception("update_employee_in_staff_roster failed")
            return {
                "success": False,
                "employee_email": employee_email,
                "location": location,
                "job_category": job_category or current_job_category,
                "error": str(exc),
            }
