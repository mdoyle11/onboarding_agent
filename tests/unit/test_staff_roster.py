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
        employee_name="Alice Example",
        work_location="Bronx",
        job_title="Teacher",
    )

    facts = card["body"][2]["facts"]
    assert {"title": "Employee", "value": "Alice Example"} in facts
    assert {"title": "Email", "value": "alice@example.com"} in facts
    assert {"title": "Location", "value": "Bronx"} in facts
    assert {"title": "Job Title", "value": "Teacher"} in facts
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
        submission_id="sub-123",
        work_location="Bronx",
        job_title="Teacher",
    )

    action_data = {action["title"]: action["data"] for action in card["actions"]}
    assert action_data["Send Welcome Email"]["submission_id"] == "sub-123"
    assert action_data["Send Welcome Email"]["work_location"] == "Bronx"
    assert action_data["Send Welcome Email"]["job_title"] == "Teacher"
    assert action_data["Create Offer Letter Draft"]["submission_id"] == "sub-123"
    assert action_data["Create Offer Letter Draft"]["work_location"] == "Bronx"
    assert action_data["Create Offer Letter Draft"]["job_title"] == "Teacher"


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
        submission_id="",
    )
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Added to Staff Roster",
        location="Bronx",
        job_title="Teacher",
        status_change="",
        submission_id="",
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
async def test_execute_new_hire_card_action_without_context_creates_docusign_draft_from_tracker_and_posts_reply():
    card_action = {
        "action": "create_docusign_draft",
        "employee_email": "alice@example.com",
        "submission_id": "sub-123",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
    docusign.create_envelope_draft.return_value = {"success": True, "envelope_id": "env-123", "status": "created"}
    docusign.create_envelope_edit_view.return_value = {"success": True, "url": "https://review.example.com/env-123"}
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "email": "alice@example.com",
        "location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
        "start_date": "2026-04-10",
    }
    card_state = {"channel_id": "channel-1", "message_id": "root-msg", "employee_name": "Alice Example", "submission_id": "sub-123"}

    with (
        patch("onboarding_agent.integrations.teams.card_actions.mark_new_hire_action_complete", new=AsyncMock()) as mark_complete,
        patch("onboarding_agent.integrations.teams.card_actions.refresh_new_hire_card", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.integrations.teams.card_actions.get_new_hire_card", new=AsyncMock(return_value=card_state)),
        patch("onboarding_agent.integrations.teams.card_actions.save_docusign_status_card", new=AsyncMock()) as save_card,
        patch(
            "onboarding_agent.integrations.teams.messenger.TeamsMessenger.send_channel_notification",
            new=AsyncMock(return_value={"success": True, "message_id": "reply-msg"}),
        ) as send_reply,
        patch("onboarding_agent.integrations.teams.card_actions.DocuSignClient", create=True),
        patch("onboarding_agent.integrations.docusign_client.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
    ):
        result = await execute_new_hire_card_action_without_context(card_action)

    assert result is True
    tracker.find_employee_in_tracker.assert_awaited_once_with("alice@example.com", submission_id="sub-123")
    docusign.create_envelope_draft.assert_awaited_once_with(
        employee_name="Alice Example",
        employee_email="alice@example.com",
        start_date="2026-04-10",
        position="Teacher",
        work_location="Bronx",
        status_change="New Hire",
        submission_id="sub-123",
    )
    send_reply.assert_awaited_once()
    send_kwargs = send_reply.await_args.kwargs
    assert send_kwargs["reply_to_id"] == "root-msg"
    assert send_kwargs["session_context"]["employee_email"] == "alice@example.com"
    assert send_kwargs["session_context"]["employee_name"] == "Alice Example"
    assert send_kwargs["session_context"]["work_location"] == "Bronx"
    assert send_kwargs["session_context"]["job_title"] == "Teacher"
    assert send_kwargs["session_context"]["status_change"] == "New Hire"
    save_card.assert_awaited_once()
    mark_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_new_hire_card_action_without_context_tolerates_missing_reply_message_id():
    card_action = {
        "action": "create_docusign_draft",
        "employee_email": "alice@example.com",
        "submission_id": "sub-123",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
    docusign.create_envelope_draft.return_value = {"success": True, "envelope_id": "env-123", "status": "created"}
    docusign.create_envelope_edit_view.return_value = {"success": True, "url": "https://review.example.com/env-123"}
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "email": "alice@example.com",
        "location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
        "start_date": "2026-04-10",
    }
    card_state = {"channel_id": "channel-1", "message_id": "root-msg", "employee_name": "Alice Example", "submission_id": "sub-123"}

    with (
        patch("onboarding_agent.integrations.teams.card_actions.mark_new_hire_action_complete", new=AsyncMock()) as mark_complete,
        patch("onboarding_agent.integrations.teams.card_actions.refresh_new_hire_card", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.integrations.teams.card_actions.get_new_hire_card", new=AsyncMock(return_value=card_state)),
        patch("onboarding_agent.integrations.teams.card_actions.save_docusign_status_card", new=AsyncMock()) as save_card,
        patch(
            "onboarding_agent.integrations.teams.messenger.TeamsMessenger.send_channel_notification",
            new=AsyncMock(return_value={"success": True, "message_id": ""}),
        ),
        patch("onboarding_agent.integrations.teams.card_actions.DocuSignClient", create=True),
        patch("onboarding_agent.integrations.docusign_client.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
    ):
        result = await execute_new_hire_card_action_without_context(card_action)

    assert result is True
    save_card.assert_awaited_once()
    assert save_card.await_args.kwargs["message_id"] == ""
    mark_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_new_hire_card_action_sends_existing_docusign_reply_card():
    card_action = {
        "action": "send_docusign",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
    }
    docusign = AsyncMock()
    docusign.send_envelope.return_value = {"success": True, "envelope_id": "env-456", "status": "sent"}
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    docusign_card = {
        "channel_id": "channel-1",
        "message_id": "reply-msg",
        "envelope_id": "env-456",
        "review_url": "https://review.example.com/env-456",
    }

    with (
        patch("onboarding_agent.integrations.teams.card_actions.get_docusign_status_card", new=AsyncMock(return_value=docusign_card)),
        patch("onboarding_agent.integrations.teams.card_actions.save_docusign_status_card", new=AsyncMock()) as save_card,
        patch("onboarding_agent.integrations.teams.card_actions.refresh_docusign_status_card", new=AsyncMock(return_value={"success": True})) as refresh_card,
        patch("onboarding_agent.integrations.teams.card_actions.DocuSignClient", create=True),
        patch("onboarding_agent.integrations.docusign_client.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.integrations.workbook.tracker_client.TrackerClient", return_value=tracker),
    ):
        result = await execute_new_hire_card_action_without_context(card_action)

    assert result is True
    docusign.send_envelope.assert_awaited_once_with("env-456")
    save_card.assert_awaited_once()
    refresh_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_staff_roster_client_verifies_write_before_success():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Group", "Location"]
    roster_rows = [
        roster_header,
        ["Existing Teacher", "existing@company.org", "Teacher", "Bronx"],
        ["Totals", "1", "Teacher", "Bronx"],
    ]
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
                    roster_rows,
                        [capacity_header, ["Teacher", "2"]],
                    roster_rows,
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
async def test_check_staff_roster_capacity_normalizes_plural_group_name():
    client = StaffRosterClient()
    capacity_rows = [["Group", "Capacity"], ["Teacher", "15"]]
    roster_rows = [["Employee Name", "Work Email", "Group"], ["Alice Example", "alice@example.com", "Teacher"]]

    with (
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
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(side_effect=[capacity_rows, roster_rows]),
        ),
    ):
        result = await client.check_staff_roster_capacity("Collier", "Teachers")

    assert result["success"] is True
    assert result["job_category"] == "Teacher"
    assert result["current_count"] == 1


@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_inserts_above_group_totals():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"]
    roster_rows_before = [
        roster_header,
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx"],
        ["Totals", "1", "", "Teacher", "", "Bronx"],
        ["Bob Example", "bob@company.org", "bob@example.com", "Auxiliary", "Custodian", "Bronx"],
        ["Totals", "1", "", "Auxiliary", "", "Bronx"],
    ]
    roster_rows_after = [
        roster_header,
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx"],
        ["Carol Example", "carol@example.com", "carol@example.com", "Teacher", "Teacher", "Bronx"],
        ["Totals", "2", "", "Teacher", "", "Bronx"],
        ["Bob Example", "bob@company.org", "bob@example.com", "Auxiliary", "Custodian", "Bronx"],
        ["Totals", "1", "", "Auxiliary", "", "Bronx"],
    ]
    capacity_rows = [["Group", "Capacity"], ["Teacher", "5"]]
    graph = AsyncMock(return_value={})

    with (
        patch.object(
            TrackerClient,
            "find_employee_in_tracker",
            new=AsyncMock(
                return_value={
                    "found": True,
                    "name": "Carol Example",
                    "email": "carol@example.com",
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
                    roster_rows_before,
                    capacity_rows,
                    roster_rows_before,
                    roster_rows_after,
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
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.add_employee_to_staff_roster(
            "carol@example.com",
            "Teacher",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
        )

    assert result["success"] is True
    insert_call = graph.await_args_list[0]
    assert insert_call.args[0] == "POST"
    assert "/range(address='A3%3AF3')/insert" in insert_call.args[1]
    assert insert_call.args[2] == {"shift": "Down"}
    patch_call = graph.await_args_list[1]
    assert patch_call.args[0] == "PATCH"
    assert "/range(address='A3%3AF3')" in patch_call.args[1]


@pytest.mark.asyncio
async def test_add_employee_to_staff_roster_relaxes_tracker_job_title_when_location_unique():
    client = StaffRosterClient()
    roster_rows = [
        ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"],
        ["Totals", "0", "", "Teacher", "", "Collier"],
    ]
    capacity_rows = [["Group", "Capacity"], ["Teacher", "2"]]
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.side_effect = [
        {"found": False, "row_id": "", "stages": {}},
        {
            "found": True,
            "name": "Matt",
            "email": "mdoyle@bridgeprepacademy.com",
            "location": "Collier",
            "job_title": "Teacher",
            "position": "Teacher",
            "start_date": "",
            "manager_email": "",
        },
    ]

    with (
        patch("onboarding_agent.integrations.workbook.staff_roster_client.TrackerClient", return_value=tracker),
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
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(side_effect=[
                roster_rows,
                capacity_rows,
                roster_rows,
                [
                    roster_rows[0],
                    ["Matt", "mdoyle@bridgeprepacademy.com", "mdoyle@bridgeprepacademy.com", "Teacher", "Teacher", "Collier"],
                    ["Totals", "1", "", "Teacher", "", "Collier"],
                ],
            ]),
        ),
        patch.object(client, "_insert_roster_row", new=AsyncMock()),
        patch.object(client, "_graph_workbook_request", new=AsyncMock(return_value={})),
    ):
        result = await client.add_employee_to_staff_roster(
            "mdoyle@bridgeprepacademy.com",
            "Teacher",
            location="Collier",
            job_title="Instructional Coach",
            status_change="New Hire",
        )

    assert result["success"] is True
    assert tracker.find_employee_in_tracker.await_args_list[0].kwargs["job_title"] == "Instructional Coach"
    assert tracker.find_employee_in_tracker.await_args_list[1].kwargs["job_title"] == ""


@patch("onboarding_agent.mcp_server.tools_staff_roster._tracker")
@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@pytest.mark.asyncio
async def test_remove_employee_from_staff_roster_clears_tracker_stage(
    mock_staff_roster_factory,
    mock_tracker_factory,
):
    staff_roster = AsyncMock()
    staff_roster.remove_employee_from_staff_roster.return_value = {
        "success": True,
        "location": "Bronx",
        "job_category": "Teacher",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    mock_staff_roster_factory.return_value = staff_roster
    mock_tracker_factory.return_value = tracker

    mcp = FastMCP(name="test-roster-remove")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "remove_employee_from_staff_roster")
    result = await tool_fn(
        employee_email="alice@example.com",
        location="Bronx",
        job_category="Teacher",
        job_title="Teacher",
        status_change="New Hire",
    )

    staff_roster.remove_employee_from_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        job_category="Teacher",
        job_title="Teacher",
        status_change="New Hire",
        submission_id="",
    )
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Added to Staff Roster",
        value="",
        location="Bronx",
        job_title="Teacher",
        status_change="New Hire",
        submission_id="",
    )
    assert result["action"] == "removed"


@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@pytest.mark.asyncio
async def test_update_employee_in_staff_roster_returns_summary(
    mock_staff_roster_factory,
):
    staff_roster = AsyncMock()
    staff_roster.update_employee_in_staff_roster.return_value = {
        "success": True,
        "location": "Bronx",
        "job_category": "Teacher",
    }
    mock_staff_roster_factory.return_value = staff_roster

    mcp = FastMCP(name="test-roster-update")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "update_employee_in_staff_roster")
    result = await tool_fn(
        employee_email="alice@example.com",
        location="Bronx",
        current_job_category="teacher",
        job_category="Teacher",
    )

    staff_roster.update_employee_in_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        current_job_category="teacher",
        job_title="",
        status_change="",
        submission_id="",
        employee_id="",
        job_category="Teacher",
        position="",
        work_email="",
        personal_email="",
        employee_name="",
        grade_level="",
        subject="",
        supplements="",
        talent="",
        background_eligibility="",
        date_approved="",
        license_value="",
        nine_cell="",
        notes="",
        roster_status="",
        nti_culture="",
        nti_content="",
        mupd_culture="",
        mupd_content="",
        rt_boy_pd_content="",
        cc_1="",
        cc_2="",
        cc_3="",
    )
    assert result["action"] == "updated"


@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@pytest.mark.asyncio
async def test_find_employee_in_staff_roster_tool_returns_extended_fields(
    mock_staff_roster_factory,
):
    staff_roster = AsyncMock()
    staff_roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "employee_id": "2101",
        "employee_email": "alice@company.org",
        "personal_email": "alice@example.com",
        "employee_name": "Alice Example",
        "job_category": "Teacher",
        "status": "Active",
    }
    mock_staff_roster_factory.return_value = staff_roster

    mcp = FastMCP(name="test-roster-find")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "find_employee_in_staff_roster")
    result = await tool_fn(employee_email="alice@example.com", location="Bronx")

    assert result["found"] is True
    assert result["employee_id"] == "2101"
    assert result["status"] == "Active"


@pytest.mark.asyncio
async def test_remove_employee_from_staff_roster_deletes_matching_row():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"]
    roster_rows = [
        roster_header,
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx"],
        ["Totals", "1", "", "Teacher", "", "Bronx"],
    ]
    graph = AsyncMock(return_value={})

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
                }
            ),
        ),
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(return_value=roster_rows),
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
        patch.object(
            client,
            "find_employee_in_staff_roster",
            new=AsyncMock(
                side_effect=[
                    {"found": True, "row_id": "2", "job_category": "Teacher"},
                    {"found": False},
                ]
            ),
        ),
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.remove_employee_from_staff_roster(
            "alice@example.com",
            location="Bronx",
            job_category="Teacher",
            job_title="Teacher",
            status_change="New Hire",
        )

    assert result["success"] is True
    delete_call = graph.await_args_list[0]
    assert delete_call.args[0] == "POST"
    assert "/range(address='A2%3AF2')/delete" in delete_call.args[1]
    assert delete_call.args[2] == {"shift": "Up"}


@pytest.mark.asyncio
async def test_update_employee_in_staff_roster_patches_existing_row():
    client = StaffRosterClient()
    roster_header = ["Employee ID", "Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location", "Status"]
    roster_rows = [
        roster_header,
        ["", "Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx", ""],
        ["", "Totals", "1", "", "Teacher", "", "Bronx", ""],
    ]
    graph = AsyncMock(return_value={})

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
                }
            ),
        ),
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(return_value=roster_rows),
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
        patch.object(
            client,
            "find_employee_in_staff_roster",
            new=AsyncMock(
                side_effect=[
                    {"found": True, "row_id": "2", "job_category": "Teacher"},
                    {"found": True, "row_id": "2", "job_category": "Teacher"},
                ]
            ),
        ),
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.update_employee_in_staff_roster(
            "alice@example.com",
            location="Bronx",
            current_job_category="Teacher",
            employee_id="2101",
            position="Lead Teacher",
            roster_status="Active",
        )

    assert result["success"] is True
    patch_call = graph.await_args_list[0]
    assert patch_call.args[0] == "PATCH"
    assert "/range(address='A2%3AH2')" in patch_call.args[1]
    written_row = patch_call.args[2]["values"][0]
    assert written_row[0] == "2101"


@pytest.mark.asyncio
async def test_update_employee_in_staff_roster_moves_to_new_group_section():
    client = StaffRosterClient()
    roster_header = ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"]
    roster_rows = [
        roster_header,
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Bronx"],
        ["Totals", "1", "", "Teacher", "", "Bronx"],
        ["Bob Example", "bob@company.org", "bob@example.com", "Auxiliary", "Custodian", "Bronx"],
        ["Totals", "1", "", "Auxiliary", "", "Bronx"],
    ]
    graph = AsyncMock(return_value={})

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
                }
            ),
        ),
        patch.object(
            client,
            "_used_range_rows",
            new=AsyncMock(
                side_effect=[
                    roster_rows,
                    [["Group", "Capacity"], ["Auxiliary", "5"]],
                    roster_rows,
                    roster_rows,
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
        patch.object(
            client,
            "find_employee_in_staff_roster",
            new=AsyncMock(
                side_effect=[
                    {"found": True, "row_id": "2", "job_category": "Teacher"},
                    {"found": True, "row_id": "4", "job_category": "Auxiliary"},
                ]
            ),
        ),
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.update_employee_in_staff_roster(
            "alice@example.com",
            location="Bronx",
            current_job_category="Teacher",
            job_category="Auxiliary",
        )

    assert result["success"] is True
    assert graph.await_args_list[0].args[0] == "POST"
    assert "/insert" in graph.await_args_list[0].args[1]
    assert graph.await_args_list[2].args[0] == "POST"
    assert "/delete" in graph.await_args_list[2].args[1]


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
        submission_id="",
    )
    staff_roster.add_employee_to_staff_roster.assert_not_awaited()
    context.send_activity.assert_awaited()
    assert "already contains" in context.send_activity.await_args.args[0]
