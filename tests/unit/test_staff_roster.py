"""Tests for staff roster helpers and Teams card actions."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from onboarding_agent.integrations.adaptive_cards import docusign_status_card, new_hire_card
from onboarding_agent.integrations.graph_workbook import _column_letter, _header_map
from onboarding_agent.integrations.teams.card_actions import card_action_to_command
from onboarding_agent.mcp_server.tools_staff_roster import register


def test_column_letter_supports_multi_letter_ranges():
    assert _column_letter(0) == "A"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"


def test_header_map_matches_normalized_staff_roster_headers():
    header = ["Employee Name", "Employee Email", "Group", "Start Date"]
    aliases = {
        "name": {"employee name"},
        "email": {"employee email"},
        "group": {"job category", "group"},
        "start_date": {"start date"},
    }
    assert _header_map(header, aliases) == {
        "name": 0,
        "email": 1,
        "group": 2,
        "start_date": 3,
    }


def test_completed_docusign_card_includes_staff_roster_action():
    card = docusign_status_card(
        employee_email="alice@example.com",
        envelope_id="env-123",
        status="completed",
        summary="Signed.",
        work_location="Bronx",
        job_title="Teacher",
    )

    assert any(action.get("title") == "Add To Staff Roster" for action in card["actions"])
    assert any(block.get("id") == "job_category" for block in card["body"])
    roster_action = next(action for action in card["actions"] if action.get("title") == "Add To Staff Roster")
    assert roster_action["data"]["work_location"] == "Bronx"
    assert roster_action["data"]["job_title"] == "Teacher"


def test_card_action_to_command_uses_exact_job_category():
    command = card_action_to_command(
        {
            "action": "add_to_staff_roster",
            "employee_email": "alice@example.com",
            "job_category": "Teacher",
        }
    )
    assert command == "add alice@example.com to the staff roster using the exact job category Teacher"


def test_new_hire_card_actions_include_composite_identity():
    card = new_hire_card(
        employee_name="Alice Example",
        employee_email="alice@example.com",
        summary="Summary",
        work_location="Bronx",
        job_title="Teacher",
    )

    action_data = {action["title"]: action["data"] for action in card["actions"]}
    assert action_data["Send Welcome Email"]["work_location"] == "Bronx"
    assert action_data["Send Welcome Email"]["job_title"] == "Teacher"
    assert action_data["Send Offer Letter"]["work_location"] == "Bronx"
    assert action_data["Send Offer Letter"]["job_title"] == "Teacher"


async def _get_tool_fn(mcp, tool_name: str):
    tool = await mcp.get_tool(tool_name)
    if tool is None:
        raise KeyError(tool_name)
    return tool.fn


@patch("onboarding_agent.mcp_server.tools_staff_roster._tracker")
@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@patch("onboarding_agent.integrations.card_state.refresh_docusign_status_card", new_callable=AsyncMock)
@patch("onboarding_agent.integrations.card_state.mark_docusign_roster_complete")
@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_marks_tracker_stage(
    mock_mark_card,
    mock_refresh_card,
    mock_staff_roster_factory,
    mock_tracker_factory,
):
    staff_roster = AsyncMock()
    staff_roster.add_employee_to_staff_roster.return_value = {"success": True}
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    mock_staff_roster_factory.return_value = staff_roster
    mock_tracker_factory.return_value = tracker
    mock_mark_card.return_value = None

    mcp = FastMCP(name="test-roster")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "add_employee_to_staff_roster")
    await tool_fn(
        employee_email="alice@example.com",
        job_category="Teacher",
        location="Bronx",
        job_title="Teacher",
    )

    staff_roster.add_employee_to_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        "Teacher",
        location="Bronx",
        job_title="Teacher",
        status_change="",
    )
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Added to Staff Roster",
        location="Bronx",
        job_title="Teacher",
        status_change="",
    )
    mock_refresh_card.assert_not_awaited()


@patch("onboarding_agent.mcp_server.tools_staff_roster._tracker")
@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@patch("onboarding_agent.integrations.card_state.refresh_docusign_status_card", new_callable=AsyncMock)
@patch("onboarding_agent.integrations.card_state.mark_docusign_roster_complete")
@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_surfaces_multiple_matches(
    mock_mark_card,
    mock_refresh_card,
    mock_staff_roster_factory,
    mock_tracker_factory,
):
    staff_roster = AsyncMock()
    staff_roster.add_employee_to_staff_roster.return_value = {
        "success": False,
        "multiple_matches": True,
        "error": "Multiple onboarding tracker rows matched alice@example.com. Pass location and job_title to disambiguate.",
        "matches": [
            {
                "row_id": "12",
                "email": "alice@example.com",
                "location": "Bronx",
                "job_title": "Teacher",
                "added_to_tracker": "2026-04-01",
            }
        ],
    }
    tracker = AsyncMock()
    mock_staff_roster_factory.return_value = staff_roster
    mock_tracker_factory.return_value = tracker
    mock_mark_card.return_value = None

    mcp = FastMCP(name="test-roster-ambiguous")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "add_employee_to_staff_roster")
    result = await tool_fn(employee_email="alice@example.com", job_category="Teacher")

    assert result["success"] is False
    assert result["multiple_matches"] is True
    assert "disambiguate" in result["error"]
    tracker.update_stage.assert_not_awaited()
    mock_refresh_card.assert_not_awaited()
