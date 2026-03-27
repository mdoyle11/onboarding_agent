"""Tests for staff roster helpers and Teams card actions."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from onboarding_agent.integrations.adaptive_cards import docusign_status_card
from onboarding_agent.integrations.graph_client import _column_letter, _header_map
from onboarding_agent.integrations.teams_bot import _card_action_to_command
from onboarding_agent.mcp_server.tools_graph import register


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
    )

    assert any(action.get("title") == "Add To Staff Roster" for action in card["actions"])
    assert any(block.get("id") == "job_category" for block in card["body"])


def test_card_action_to_command_uses_exact_job_category():
    command = _card_action_to_command(
        {
            "action": "add_to_staff_roster",
            "employee_email": "alice@example.com",
            "job_category": "Teacher",
        }
    )
    assert command == "add alice@example.com to the staff roster using the exact job category Teacher"


async def _get_tool_fn(mcp, tool_name: str):
    tool = await mcp.get_tool(tool_name)
    if tool is None:
        raise KeyError(tool_name)
    return tool.fn


@patch("onboarding_agent.mcp_server.tools_graph._tracker")
@patch("onboarding_agent.integrations.card_state.refresh_docusign_status_card", new_callable=AsyncMock)
@patch("onboarding_agent.integrations.card_state.mark_docusign_roster_complete")
@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_marks_tracker_stage(
    mock_mark_card,
    mock_refresh_card,
    mock_tracker_factory,
):
    tracker = AsyncMock()
    tracker.add_employee_to_staff_roster.return_value = {"success": True}
    tracker.update_stage.return_value = {"success": True}
    mock_tracker_factory.return_value = tracker
    mock_mark_card.return_value = None

    mcp = FastMCP(name="test-roster")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "add_employee_to_staff_roster")
    await tool_fn(employee_email="alice@example.com", job_category="Teacher")

    tracker.update_stage.assert_awaited_once_with("alice@example.com", "Added to Staff Roster")
    mock_refresh_card.assert_not_awaited()
