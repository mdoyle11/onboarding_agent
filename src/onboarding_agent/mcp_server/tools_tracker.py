"""Onboarding tracker and Forms tools."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.integrations.forms_client import FormsClient
from onboarding_agent.integrations.graph_workbook import ACTIVE_STAGES, ALL_STAGES
from onboarding_agent.integrations.tracker_client import TrackerClient

logger = logging.getLogger(__name__)

_LIST_EMPLOYEE_PREVIEW_LIMIT = 25
_DEFAULT_RECENT_DAYS = 30


def _tracker() -> TrackerClient:
    return TrackerClient()


def _compact_employee_lookup(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("found"):
        matches = result.get("matches", [])
        if isinstance(matches, list) and matches:
            lines = [
                f"  • location={m.get('location', '') or 'unknown'}, "
                f"job_title={m.get('job_title', '') or 'unknown'}, "
                f"added_to_tracker={m.get('added_to_tracker', '') or 'unknown'}"
                for m in matches
                if isinstance(m, dict)
            ]
            summary = (
                "Multiple tracker entries matched this email. "
                "Provide location and job_title to disambiguate.\n"
                + "\n".join(lines)
            )
        else:
            summary = "Employee not found in the tracker."
        return {
            "found": False,
            "row_id": "",
            "email": str(result.get("email", "") or ""),
            "status": "",
            "multiple_matches": bool(result.get("multiple_matches", False)),
            "matches": matches if isinstance(matches, list) else [],
            "error": str(result.get("error", "") or ""),
            "summary": summary,
        }

    name = str(result.get("name", "") or "")
    email = str(result.get("email", "") or "")
    status = str(result.get("status", "") or "")
    location = str(result.get("location", "") or "")
    start_date = _format_stage_date(str(result.get("start_date", "") or ""))

    summary_bits = [f"Found {name or email}"]
    if email:
        summary_bits.append(f"({email})")
    if status:
        summary_bits.append(f"status={status}")
    if location:
        summary_bits.append(f"location={location}")
    if start_date:
        summary_bits.append(f"start_date={start_date}")

    return {
        "found": True,
        "row_id": str(result.get("row_id", "") or ""),
        "name": name,
        "email": email,
        "location": location,
        "start_date": start_date,
        "job_title": str(result.get("job_title", "") or ""),
        "position": str(result.get("position", "") or result.get("job_title", "") or ""),
        "identity_key": str(result.get("identity_key", "") or ""),
        "manager_email": str(result.get("manager_email", "") or ""),
        "status": status,
        "summary": " ".join(summary_bits),
    }


def _employee_preview(employee: dict[str, Any]) -> dict[str, str]:
    stages = employee.get("stages", {}) if isinstance(employee.get("stages"), dict) else {}
    active_stage = ""
    for stage in ACTIVE_STAGES:
        if stages.get(stage):
            active_stage = stage

    return {
        "name": str(employee.get("name", "") or ""),
        "email": str(employee.get("email", "") or ""),
        "location": str(employee.get("location", "") or ""),
        "job_title": str(employee.get("job_title", "") or ""),
        "position": str(employee.get("position", "") or employee.get("job_title", "") or ""),
        "start_date": _format_stage_date(str(employee.get("start_date", "") or "")),
        "active_stage": active_stage,
    }


def _format_stage_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed.strftime("%m/%d/%Y")
        except ValueError:
            continue

    try:
        excel_serial = float(raw)
        excel_epoch = date(1899, 12, 30)
        parsed = excel_epoch.fromordinal(excel_epoch.toordinal() + int(excel_serial))
        return parsed.strftime("%m/%d/%Y")
    except ValueError:
        return raw


def _parse_tracker_date(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    try:
        excel_serial = float(raw)
        excel_epoch = date(1899, 12, 30)
        return excel_epoch.fromordinal(excel_epoch.toordinal() + int(excel_serial))
    except ValueError:
        return None


def _employee_matches_filters(
    employee: dict[str, Any],
    *,
    pending_stage: str,
    location: str,
    job_title: str,
    query: str,
    start_date_from: date | None,
    start_date_to: date | None,
) -> bool:
    stages = employee.get("stages", {}) if isinstance(employee.get("stages"), dict) else {}
    if pending_stage and stages.get(pending_stage):
        return False

    employee_location = str(employee.get("location", "") or "")
    if location and employee_location.lower() != location.lower():
        return False

    employee_job_title = str(employee.get("job_title", "") or employee.get("position", "") or "")
    if job_title and employee_job_title.lower() != job_title.lower():
        return False

    if query:
        haystacks = [
            str(employee.get("name", "") or "").lower(),
            str(employee.get("email", "") or "").lower(),
            employee_location.lower(),
            employee_job_title.lower(),
        ]
        if not any(query in haystack for haystack in haystacks):
            return False

    employee_start_date = _parse_tracker_date(str(employee.get("start_date", "") or ""))
    if start_date_from and (employee_start_date is None or employee_start_date < start_date_from):
        return False
    return not (start_date_to and (employee_start_date is None or employee_start_date > start_date_to))


def register(mcp: FastMCP) -> None:
    """Register tracker and Forms tools on the given FastMCP instance."""

    @mcp.tool()
    async def find_employee_in_tracker(
        employee_email: str,
        location: str = "",
        job_title: str = "",
    ) -> dict[str, Any]:
        result = await _tracker().find_employee_in_tracker(
            employee_email,
            location=location,
            job_title=job_title,
        )
        return _compact_employee_lookup(result)

    @mcp.tool()
    async def add_employee_to_tracker(
        staff_name: str,
        staff_email: str,
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
        return await _tracker().add_employee_to_tracker(
            staff_name=staff_name,
            staff_email=staff_email,
            requested_start_date=requested_start_date,
            job_title=job_title,
            work_location=work_location,
            requesting_manager=requesting_manager,
            status_change=status_change,
            staff_phone=staff_phone,
            education_level=education_level,
            supplements=supplements,
            license_number=license_number,
            uploaded_credentials=uploaded_credentials,
            compensation=compensation,
            employment_type=employment_type,
            contract_term=contract_term,
        )

    @mcp.tool()
    async def update_tracker_stage(employee_email: str, stage_name: str) -> dict[str, Any]:
        return await _tracker().update_stage(employee_email, stage_name)

    @mcp.tool()
    async def get_employee_stages(
        employee_email: str,
        location: str = "",
        job_title: str = "",
    ) -> dict[str, Any]:
        result = await _tracker().find_employee_in_tracker(
            employee_email,
            location=location,
            job_title=job_title,
        )

        if not result.get("found"):
            return {
                "found": False,
                "employee_email": employee_email,
                "stages": {},
                "summary": f"No record found for {employee_email} in the tracker.",
            }

        stages: dict[str, str] = result.get("stages", {})
        formatted_stages = {stage: _format_stage_date(value) for stage, value in stages.items()}
        name = result.get("name", employee_email)

        completed = [stage for stage in ALL_STAGES if formatted_stages.get(stage)]
        pending = [stage for stage in ALL_STAGES if not formatted_stages.get(stage)]
        last_completed = completed[-1] if completed else None
        next_pending = pending[0] if pending else None

        if not completed:
            summary = f"**{name}** has been added to the system but no stages are complete yet."
        elif not next_pending:
            summary = f"**{name}** has completed all pipeline stages."
        else:
            last_completed_stage = last_completed or ""
            summary = (
                f"**{name}** — last completed stage: *{last_completed_stage}* "
                f"({formatted_stages.get(last_completed_stage, '')}). Next: *{next_pending}*."
            )

        lines = [f"  • {stage}: {formatted_stages.get(stage) or 'pending'}" for stage in ACTIVE_STAGES]
        summary += "\n" + "\n".join(lines)

        return {**result, "stages": formatted_stages, "summary": summary}

    @mcp.tool()
    async def list_employees(
        pending_stage: str = "",
        location: str = "",
        job_title: str = "",
        position: str = "",
        query: str = "",
        start_date_from: str = "",
        start_date_to: str = "",
        recent_days: int = _DEFAULT_RECENT_DAYS,
        limit: int = _LIST_EMPLOYEE_PREVIEW_LIMIT,
    ) -> dict[str, Any]:
        result = await _tracker().list_all_employees()
        if not result.get("success"):
            return result

        employees = result["employees"]
        start_from = _parse_tracker_date(start_date_from)
        start_to = _parse_tracker_date(start_date_to)

        if not start_date_from and not start_date_to and recent_days > 0:
            start_from = date.today() - timedelta(days=recent_days)

        filtered = [
            employee for employee in employees
            if _employee_matches_filters(
                employee,
                pending_stage=pending_stage,
                location=location,
                job_title=job_title or position,
                query=query.strip().lower(),
                start_date_from=start_from,
                start_date_to=start_to,
            )
        ]

        preview_limit = max(1, min(limit, _LIST_EMPLOYEE_PREVIEW_LIMIT))
        preview = [_employee_preview(employee) for employee in filtered[:preview_limit]]
        remaining = max(len(filtered) - len(preview), 0)

        filter_descriptors = []
        if pending_stage:
            filter_descriptors.append(f"pending {pending_stage}")
        if location:
            filter_descriptors.append(f"location={location}")
        if job_title or position:
            filter_descriptors.append(f"job_title={job_title or position}")
        if query:
            filter_descriptors.append(f"matching '{query}'")
        if start_from:
            filter_descriptors.append(f"start_date>={start_from.isoformat()}")
        if start_to:
            filter_descriptors.append(f"start_date<={start_to.isoformat()}")

        filter_suffix = f" ({', '.join(filter_descriptors)})" if filter_descriptors else ""

        if not filtered:
            if pending_stage:
                summary = f"No employees matched **{pending_stage}**{filter_suffix}."
            else:
                summary = f"No employees matched the current filters{filter_suffix}."
        elif pending_stage:
            summary = f"**{len(filtered)} employee(s)** are pending **{pending_stage}**{filter_suffix}."
        else:
            summary = f"**{len(filtered)} employee(s)** matched the current filters{filter_suffix}."

        if preview:
            summary += "\n" + "\n".join(
                f"  • {employee['name']} ({employee['email']})"
                + (f" — {employee['active_stage']}" if employee["active_stage"] else "")
                + (f" — start {employee['start_date']}" if employee["start_date"] else "")
                for employee in preview
            )
        if remaining:
            summary += f"\n  • …and {remaining} more."

        return {
            "count": len(filtered),
            "pending_stage": pending_stage,
            "location": location,
            "job_title": job_title or position,
            "position": position,
            "query": query,
            "start_date_from": start_from.isoformat() if start_from else "",
            "start_date_to": start_to.isoformat() if start_to else "",
            "recent_days": recent_days,
            "employees": preview,
            "truncated": remaining > 0,
            "returned_count": len(preview),
            "summary": summary,
        }

    @mcp.tool()
    async def get_form_submission_by_id(submission_id: str) -> dict[str, Any]:
        return await FormsClient().get_submission_by_id(submission_id)
