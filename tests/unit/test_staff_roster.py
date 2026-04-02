"""Tests for staff roster helpers and Teams card actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from onboarding_agent.integrations.adaptive_cards import docusign_status_card, new_hire_card
from onboarding_agent.integrations.teams.card_actions import (
    execute_new_hire_card_action_without_context,
    handle_staff_roster_card_action,
)
from onboarding_agent.integrations.workbook.helpers import column_letter as _column_letter
from onboarding_agent.integrations.workbook.helpers import header_map as _header_map
from onboarding_agent.integrations.workbook.schema import HEADER_ROW
from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient
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


def _build_tracker_row(values: dict[str, str]) -> list[str]:
    header_index = {header: idx for idx, header in enumerate(HEADER_ROW)}
    row = [""] * len(HEADER_ROW)
    for header, value in values.items():
        row[header_index[header]] = value
    return row


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
    result = await tool_fn(
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
    assert result["action"] == "added"
    assert "was added" in result["summary"]
    mock_refresh_card.assert_not_awaited()


@patch("onboarding_agent.mcp_server.tools_staff_roster._tracker")
@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@patch("onboarding_agent.integrations.card_state.refresh_docusign_status_card", new_callable=AsyncMock)
@patch("onboarding_agent.integrations.card_state.mark_docusign_roster_complete")
@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_returns_already_exists_summary(
    mock_mark_card,
    mock_refresh_card,
    mock_staff_roster_factory,
    mock_tracker_factory,
):
    staff_roster = AsyncMock()
    staff_roster.add_employee_to_staff_roster.return_value = {
        "success": True,
        "already_exists": True,
        "location": "Bronx",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    mock_staff_roster_factory.return_value = staff_roster
    mock_tracker_factory.return_value = tracker
    mock_mark_card.return_value = None

    mcp = FastMCP(name="test-roster-existing")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "add_employee_to_staff_roster")
    result = await tool_fn(
        employee_email="alice@example.com",
        job_category="Teacher",
        location="Bronx",
        job_title="Teacher",
    )

    assert result["success"] is True
    assert result["action"] == "already_exists"
    assert "already existed" in result["summary"]


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


@pytest.mark.asyncio
async def test_execute_new_hire_card_action_without_context_sends_docusign_deterministically():
    card_action = {
        "action": "send_docusign",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}
    docusign.send_envelope.return_value = {"success": True, "envelope_id": "env-123", "status": "sent"}
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}

    with (
        patch("onboarding_agent.integrations.teams.card_actions.mark_new_hire_action_complete", new=AsyncMock()),
        patch("onboarding_agent.integrations.teams.card_actions.refresh_new_hire_card", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.integrations.teams.card_actions.DocuSignClient", create=True),
        patch("onboarding_agent.integrations.docusign_client.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
    ):
        result = await execute_new_hire_card_action_without_context(card_action)

    assert result is True
    docusign.check_draft_exists.assert_awaited_once_with(
        "alice@example.com",
        "Bronx",
        "Teacher",
        "New Hire",
    )
    docusign.send_envelope.assert_awaited_once_with("env-123")
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Sent Offer Letter",
        location="Bronx",
        job_title="Teacher",
        status_change="New Hire",
    )


@pytest.mark.asyncio
async def test_execute_new_hire_card_action_recreates_missing_docusign_draft_from_card_state():
    card_action = {
        "action": "send_docusign",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
    docusign.create_envelope_draft.return_value = {"success": True, "envelope_id": "env-456", "status": "created"}
    docusign.send_envelope.return_value = {"success": True, "envelope_id": "env-456", "status": "sent"}
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    card_state = {
        "employee_name": "Alice Example",
        "requested_start_date": "2026-04-10",
    }

    with (
        patch("onboarding_agent.integrations.teams.card_actions.mark_new_hire_action_complete", new=AsyncMock()),
        patch("onboarding_agent.integrations.teams.card_actions.refresh_new_hire_card", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.integrations.teams.card_actions.get_new_hire_card", new=AsyncMock(return_value=card_state)),
        patch("onboarding_agent.integrations.teams.card_actions.DocuSignClient", create=True),
        patch("onboarding_agent.integrations.docusign_client.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
    ):
        result = await execute_new_hire_card_action_without_context(card_action)

    assert result is True
    docusign.create_envelope_draft.assert_awaited_once_with(
        employee_name="Alice Example",
        employee_email="alice@example.com",
        start_date="2026-04-10",
        position="Teacher",
        work_location="Bronx",
        status_change="New Hire",
    )
    docusign.send_envelope.assert_awaited_once_with("env-456")


@pytest.mark.asyncio
async def test_staff_roster_client_verifies_write_before_success():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Group", "Location"]
    capacity_header = ["Group", "Capacity"]

    with (
        patch.object(
            TrackerClient,
            "find_employee_in_tracker",
            new=AsyncMock(
                return_value={
                    "found": True,
                    "name": "Alice Example",
                    "email": "alice@example.com",
                    "location": "Bronx",
                    "job_title": "Teacher",
                    "position": "Teacher",
                    "start_date": "2026-04-10",
                    "manager_email": "manager@example.com",
                }
            ),
        ),
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(
                side_effect=[
                    [roster_header],
                    [capacity_header, ["Teacher", "1"]],
                    [roster_header],
                    [roster_header],
                ]
            ),
        ),
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "roster_sheet_name": "Roster",
                "capacity_sheet_name": "Capacity",
            },
        ),
        patch.object(client, "_graph_workbook_request", new=AsyncMock(return_value={})),
    ):
        result = await client.add_employee_to_staff_roster(
            "alice@example.com",
            "Teacher",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
        )

    assert result["success"] is False
    assert "did not verify" in result["error"]


@pytest.mark.asyncio
async def test_find_employee_in_staff_roster_falls_back_to_name_and_position_when_email_changes():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"]
    roster_row = ["Alice Example", "alice@company.org", "", "Teacher", "Teacher", "Bronx"]

    with (
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(return_value=[roster_header, roster_row]),
        ),
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "roster_sheet_name": "Roster",
                "capacity_sheet_name": "Capacity",
            },
        ),
    ):
        result = await client.find_employee_in_staff_roster(
            "alice@example.com",
            location="Bronx",
            personal_email="alice@example.com",
            employee_name="Alice Example",
            position="Teacher",
        )

    assert result["found"] is True
    assert result["employee_email"] == "alice@company.org"
    assert result["job_category"] == "Teacher"


@pytest.mark.asyncio
async def test_find_employee_in_staff_roster_prefers_personal_email_column():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"]
    roster_row = ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx"]

    with (
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(return_value=[roster_header, roster_row]),
        ),
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "roster_sheet_name": "Roster",
                "capacity_sheet_name": "Capacity",
            },
        ),
    ):
        result = await client.find_employee_in_staff_roster(
            "alice@example.com",
            location="Bronx",
            personal_email="alice@example.com",
            employee_name="Alice Example",
            position="Teacher",
        )

    assert result["found"] is True
    assert result["employee_email"] == "alice@company.org"
    assert result["personal_email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_handle_staff_roster_card_action_reports_capacity_failure_without_completion():
    context = AsyncMock()
    context.activity = SimpleNamespace(reply_to_id="reply-1")
    card_action = {
        "action": "add_to_staff_roster",
        "employee_email": "alice@example.com",
        "job_category": "Teacher",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }
    staff_roster = AsyncMock()
    staff_roster.find_employee_in_staff_roster.return_value = {"found": False}
    staff_roster.add_employee_to_staff_roster.return_value = {
        "success": False,
        "error": "Category 'Teacher' at Bronx is at capacity",
    }

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
        patch("onboarding_agent.integrations.workbook.staff_roster_client.StaffRosterClient", return_value=staff_roster),
        patch("onboarding_agent.integrations.teams.card_actions.mark_docusign_roster_complete", new=AsyncMock()),
    ):
        await handle_staff_roster_card_action(context, card_action)

    tracker.update_stage.assert_not_awaited()
    context.send_activity.assert_awaited()
    assert "at capacity" in context.send_activity.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_staff_roster_card_action_uses_existing_roster_membership_as_source_of_truth():
    context = AsyncMock()
    context.activity = SimpleNamespace(reply_to_id="reply-1")
    card_action = {
        "action": "add_to_staff_roster",
        "employee_email": "alice@example.com",
        "job_category": "",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }
    tracker.update_stage.return_value = {"success": True}
    staff_roster = AsyncMock()
    staff_roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "job_category": "Teacher",
    }

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
        patch("onboarding_agent.integrations.workbook.staff_roster_client.StaffRosterClient", return_value=staff_roster),
        patch("onboarding_agent.integrations.teams.card_actions.mark_docusign_roster_complete", new=AsyncMock(return_value={"message_id": "msg-1"})),
        patch("onboarding_agent.integrations.teams.card_actions._update_docusign_status_card", new=AsyncMock(return_value=True)),
        patch("onboarding_agent.integrations.teams.card_actions.refresh_card_from_context", new=AsyncMock(return_value=True)),
    ):
        await handle_staff_roster_card_action(context, card_action)

    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Added to Staff Roster",
        location="Bronx",
        job_title="Teacher",
        status_change="New Hire",
    )
    staff_roster.add_employee_to_staff_roster.assert_not_awaited()
    context.send_activity.assert_awaited()
    assert "already contains" in context.send_activity.await_args.args[0]
