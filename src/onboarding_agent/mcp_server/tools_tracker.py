"""Onboarding tracker and Forms tools."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.integrations.forms_client import FormsClient
from onboarding_agent.integrations.tracker_client import TrackerClient

logger = logging.getLogger(__name__)

_ALL_STAGES = [
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
_ACTIVE_STAGES = ["Added to Tracker", "Added to Staff Roster", "Sent Offer Letter", "Offer Letter Signed"]


def _tracker() -> TrackerClient:
    return TrackerClient()


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


def register(mcp: FastMCP) -> None:
    """Register tracker and Forms tools on the given FastMCP instance."""

    @mcp.tool()
    async def find_employee_in_tracker(employee_email: str) -> dict[str, Any]:
        return await _tracker().find_employee_in_tracker(employee_email)

    @mcp.tool()
    async def add_employee_to_tracker(
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
        location: str = "",
    ) -> dict[str, Any]:
        return await _tracker().add_employee_to_tracker(
            name,
            email,
            start_date,
            department,
            manager_email,
            location,
        )

    @mcp.tool()
    async def update_tracker_stage(employee_email: str, stage_name: str) -> dict[str, Any]:
        return await _tracker().update_stage(employee_email, stage_name)

    @mcp.tool()
    async def get_employee_stages(employee_email: str) -> dict[str, Any]:
        result = await _tracker().find_employee_in_tracker(employee_email)

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

        completed = [stage for stage in _ALL_STAGES if formatted_stages.get(stage)]
        pending = [stage for stage in _ALL_STAGES if not formatted_stages.get(stage)]
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

        lines = [f"  • {stage}: {formatted_stages.get(stage) or 'pending'}" for stage in _ACTIVE_STAGES]
        summary += "\n" + "\n".join(lines)

        return {**result, "stages": formatted_stages, "summary": summary}

    @mcp.tool()
    async def list_employees(pending_stage: str = "") -> dict[str, Any]:
        result = await _tracker().list_all_employees()
        if not result.get("success"):
            return result

        employees = result["employees"]
        if pending_stage:
            employees = [employee for employee in employees if not employee["stages"].get(pending_stage)]

        if not employees:
            if pending_stage:
                summary = f"No employees are pending **{pending_stage}** — all have completed it."
            else:
                summary = "The tracker is empty — no employees have been added yet."
        elif pending_stage:
            summary = (
                f"**{len(employees)} employee(s)** are pending **{pending_stage}**:\n"
                + "\n".join(f"  • {employee['name']} ({employee['email']})" for employee in employees)
            )
        else:
            summary = (
                f"**{len(employees)} employee(s)** in the tracker:\n"
                + "\n".join(f"  • {employee['name']} ({employee['email']})" for employee in employees)
            )

        return {
            "count": len(employees),
            "pending_stage": pending_stage,
            "employees": employees,
            "summary": summary,
        }

    @mcp.tool()
    async def get_form_submission_by_id(submission_id: str) -> dict[str, Any]:
        return await FormsClient().get_submission_by_id(submission_id)
