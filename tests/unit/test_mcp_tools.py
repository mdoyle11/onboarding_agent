"""Tests for MCP tool logic with mocked tracker and DocuSign clients."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP


async def _get_tool_fn(mcp: FastMCP, tool_name: str):
    """Extract the raw async function from a FastMCP tool (v3 async API)."""
    tool = await mcp.get_tool(tool_name)
    if tool is None:
        raise KeyError(f"Tool {tool_name!r} not found in MCP registry")
    return tool.fn


@pytest.mark.asyncio
async def test_send_new_hire_card_propagates_submission_id_into_card_and_state():
    from onboarding_agent.mcp_server.tools_teams import register

    messenger = AsyncMock()
    messenger.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    mcp = FastMCP(name="test-teams-new-hire-card")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_teams._messenger", return_value=messenger),
        patch("onboarding_agent.integrations.card_state.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.integrations.card_state.save_new_hire_card", new=AsyncMock()) as save_card,
        patch("onboarding_agent.integrations.adaptive_cards.new_hire_card", return_value={"type": "AdaptiveCard"}) as build_card,
    ):
        tool_fn = await _get_tool_fn(mcp, "send_new_hire_card")
        await tool_fn(
            channel_id="channel-1",
            employee_name="Alice Example",
            employee_email="alice@example.com",
            summary="Summary",
            submission_id="sub-123",
            title="New Hire Requested",
            status_change="New Hire",
            requested_start_date="2026-04-10",
            job_title="Teacher",
            work_location="Bronx",
            requesting_manager="Manager",
        )

    assert build_card.call_count == 1
    assert build_card.call_args.kwargs["submission_id"] == "sub-123"
    assert messenger.send_channel_notification.await_args.kwargs["session_context"]["submission_id"] == "sub-123"
    assert save_card.await_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_record_separation_surfaces_roster_multiple_matches() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.find_employee_in_staff_roster.return_value = {
        "found": False,
        "multiple_matches": True,
        "matches": [
            {"row_id": "10", "job_category": "Teacher", "position": "Teacher"},
            {"row_id": "11", "job_category": "Teacher Assistant", "position": "Teacher"},
        ],
    }
    tracker = AsyncMock()
    tracker.resolve_employee_relaxed.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }

    mcp = FastMCP(name="test-separation-ambiguous")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=AsyncMock()),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            status_change="Separation",
        )

    assert result["success"] is False
    assert result["multiple_matches"] is True
    assert len(result["matches"]) == 2
    assert "Multiple staff roster rows matched this employee" in result["error"]


@pytest.mark.asyncio
async def test_update_leave_status_surfaces_roster_multiple_matches() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.update_employee_leave_status.return_value = {
        "success": False,
        "multiple_matches": True,
        "matches": [
            {"row_id": "10", "job_category": "Teacher", "position": "Teacher"},
            {"row_id": "11", "job_category": "Teacher Assistant", "position": "Teacher"},
        ],
        "error": "Multiple staff roster rows matched this employee.",
    }

    mcp = FastMCP(name="test-leave-ambiguous")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=AsyncMock()),
    ):
        tool_fn = await _get_tool_fn(mcp, "update_leave_status")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            status="On Leave",
            status_change="Leave Start",
        )

    assert result["success"] is False
    assert result["multiple_matches"] is True
    assert len(result["matches"]) == 2
    assert "Multiple staff roster rows matched this employee" in result["summary"]


@patch("onboarding_agent.mcp_server.tools_tracker._tracker")
@pytest.mark.asyncio
async def test_update_tracker_field_resolves_relaxed_column_name(mock_tracker_factory) -> None:
    from onboarding_agent.mcp_server.tools_tracker import register

    tracker = AsyncMock()
    tracker.update_employee_in_tracker.return_value = {"success": True, "employee_email": "alice@example.com"}
    mock_tracker_factory.return_value = tracker

    mcp = FastMCP(name="test-update-tracker-field")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "update_tracker_field")
    result = await tool_fn(
        employee_email="alice@example.com",
        column_name="start date",
        value="2026-08-03",
        location="Bronx",
    )

    assert result["success"] is True
    assert result["field"] == "requested_start_date"
    tracker.update_employee_in_tracker.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        current_job_title="",
        current_status_change="",
        submission_id="",
        requested_start_date="2026-08-03",
    )


@patch("onboarding_agent.mcp_server.tools_tracker._tracker")
@pytest.mark.asyncio
async def test_update_tracker_field_rejects_stage_column(mock_tracker_factory) -> None:
    from onboarding_agent.mcp_server.tools_tracker import register

    tracker = AsyncMock()
    mock_tracker_factory.return_value = tracker

    mcp = FastMCP(name="test-update-tracker-field-stage")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "update_tracker_field")
    result = await tool_fn(
        employee_email="alice@example.com",
        column_name="Background Submission",
        value="2026-08-03",
    )

    assert result["success"] is False
    assert result["blocked"] is True
    assert "update-stage" in result["error"]
    tracker.update_employee_in_tracker.assert_not_awaited()


@patch("onboarding_agent.mcp_server.tools_staff_roster._staff_roster")
@pytest.mark.asyncio
async def test_update_staff_roster_field_resolves_relaxed_column_name(mock_staff_roster_factory) -> None:
    from onboarding_agent.mcp_server.tools_staff_roster import register

    staff_roster = AsyncMock()
    staff_roster.update_employee_in_staff_roster.return_value = {"success": True, "employee_email": "alice@example.com"}
    mock_staff_roster_factory.return_value = staff_roster

    mcp = FastMCP(name="test-update-roster-field")
    register(mcp)
    tool_fn = await _get_tool_fn(mcp, "update_staff_roster_field")
    result = await tool_fn(
        employee_email="alice@example.com",
        location="Collier",
        column_name="grade",
        value="3",
    )

    assert result["success"] is True
    assert result["field"] == "grade_level"
    staff_roster.update_employee_in_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        location="Collier",
        current_job_category="",
        job_title="",
        status_change="",
        submission_id="",
        grade_level="3",
    )


@pytest.mark.asyncio
async def test_record_separation_continues_when_separation_entry_already_exists() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "employee_name": "Alice Example",
        "employee_email": "alice@company.org",
        "personal_email": "alice@example.com",
        "job_category": "Teacher",
        "position": "Teacher",
    }
    roster.remove_employee_from_staff_roster.return_value = {"success": True}
    separations = AsyncMock()
    separations.add_separation_record.return_value = {
        "success": True,
        "already_exists": True,
        "action": "already_exists",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}
    tracker.resolve_employee_relaxed.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }

    mcp = FastMCP(name="test-separation-existing")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
        patch("onboarding_agent.integrations.card_state.mark_separation_action_complete", new=AsyncMock(return_value=None)),
        patch("onboarding_agent.integrations.card_state.refresh_separation_card", new=AsyncMock()),
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            job_title="Teacher",
            status_change="Separation",
            submission_id="sub-123",
        )

    assert result["success"] is True
    assert result["already_exists"] is True
    roster.remove_employee_from_staff_roster.assert_awaited_once()
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Added to Staff Roster",
        location="Bronx",
        job_title="Teacher",
        status_change="Separation",
        submission_id="sub-123",
    )
    assert "already existed" in result["summary"]


@pytest.mark.asyncio
async def test_record_separation_requires_status_change_for_natural_language_request() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    separations = AsyncMock()
    tracker = AsyncMock()

    mcp = FastMCP(name="test-separation-clarification")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            job_title="Teacher",
        )

    assert result["success"] is False
    assert result["action"] == "needs_clarification"
    assert result["needs_clarification"] is True
    assert "Separation or Transfer Out" in result["summary"]
    roster.find_employee_in_staff_roster.assert_not_awaited()
    separations.add_separation_record.assert_not_awaited()
    tracker.update_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_separation_refreshes_matching_adaptive_card_on_success() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "employee_name": "Alice Example",
        "employee_email": "alice@company.org",
        "personal_email": "alice@example.com",
        "job_category": "Teacher",
        "position": "Teacher",
    }
    roster.remove_employee_from_staff_roster.return_value = {"success": True}
    separations = AsyncMock()
    separations.add_separation_record.return_value = {"success": True, "action": "added"}
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True}

    mcp = FastMCP(name="test-separation-card-refresh")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
        patch(
            "onboarding_agent.integrations.card_state.mark_separation_action_complete",
            new=AsyncMock(return_value={"message_id": "msg-1"}),
        ) as mark_complete,
        patch("onboarding_agent.integrations.card_state.refresh_separation_card", new=AsyncMock()) as refresh_card,
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            job_title="Teacher",
            status_change="Transfer Out",
            submission_id="sub-123",
        )

    assert result["success"] is True
    mark_complete.assert_awaited_once()
    refresh_card.assert_awaited_once()
    assert refresh_card.await_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_record_separation_requires_clarification_for_multiple_active_cards(tmp_path) -> None:
    from onboarding_agent.integrations.card_state import save_separation_card
    from onboarding_agent.mcp_server.tools_separations import register
    from onboarding_agent.runtime import state_store as store_mod
    from onboarding_agent.runtime.state_store import FileStateStore

    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_separation_card(
            employee_email="alice@example.com",
            employee_name="Alice Example",
            channel_id="channel-1",
            message_id="msg-1",
            submission_id="sub-1",
            status_change="Transfer Out",
            job_title="Teacher",
            work_location="Bronx",
        )
        await save_separation_card(
            employee_email="alice@example.com",
            employee_name="Alice Example",
            channel_id="channel-1",
            message_id="msg-2",
            submission_id="sub-2",
            status_change="Transfer Out",
            job_title="Coach",
            work_location="Bronx",
        )

        roster = AsyncMock()
        separations = AsyncMock()
        tracker = AsyncMock()

        mcp = FastMCP(name="test-separation-active-card-ambiguity")
        register(mcp)

        with (
            patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
            patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
            patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
        ):
            tool_fn = await _get_tool_fn(mcp, "record_separation")
            result = await tool_fn(
                employee_email="alice@example.com",
                location="Bronx",
                status_change="Transfer Out",
            )

        assert result["success"] is False
        assert result["needs_clarification"] is True
        assert result["multiple_active_cards"] is True
        assert len(result["matches"]) == 2
        roster.find_employee_in_staff_roster.assert_not_awaited()
        separations.add_separation_record.assert_not_awaited()
        tracker.update_stage.assert_not_awaited()
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_record_separation_uses_single_active_card_context_for_refresh(tmp_path) -> None:
    from onboarding_agent.integrations.card_state import save_separation_card
    from onboarding_agent.mcp_server.tools_separations import register
    from onboarding_agent.runtime import state_store as store_mod
    from onboarding_agent.runtime.state_store import FileStateStore

    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_separation_card(
            employee_email="alice@example.com",
            employee_name="Alice Example",
            channel_id="channel-1",
            message_id="msg-1",
            submission_id="sub-123",
            status_change="Transfer Out",
            job_title="Teacher",
            work_location="Bronx",
        )

        roster = AsyncMock()
        roster.find_employee_in_staff_roster.return_value = {
            "found": True,
            "employee_name": "Alice Example",
            "employee_email": "alice@company.org",
            "personal_email": "alice@example.com",
            "job_category": "Teacher",
            "position": "Teacher",
        }
        roster.remove_employee_from_staff_roster.return_value = {"success": True}
        separations = AsyncMock()
        separations.add_separation_record.return_value = {"success": True, "action": "added"}
        tracker = AsyncMock()
        tracker.update_stage.return_value = {"success": True}

        mcp = FastMCP(name="test-separation-single-active-card-context")
        register(mcp)

        with (
            patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
            patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
            patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
            patch(
                "onboarding_agent.integrations.card_state.mark_separation_action_complete",
                new=AsyncMock(return_value={"message_id": "msg-1"}),
            ) as mark_complete,
            patch("onboarding_agent.integrations.card_state.refresh_separation_card", new=AsyncMock()) as refresh_card,
        ):
            tool_fn = await _get_tool_fn(mcp, "record_separation")
            result = await tool_fn(
                employee_email="alice@example.com",
                location="Bronx",
                status_change="Transfer Out",
            )

        assert result["success"] is True
        roster.find_employee_in_staff_roster.assert_awaited_once_with(
            "alice@example.com",
            location="Bronx",
            job_category="",
            personal_email="alice@example.com",
            position="Teacher",
        )
        tracker.update_stage.assert_awaited_once_with(
            "alice@example.com",
            "Added to Staff Roster",
            location="Bronx",
            job_title="Teacher",
            status_change="Transfer Out",
            submission_id="sub-123",
        )
        mark_complete.assert_awaited_once()
        assert mark_complete.await_args.kwargs["submission_id"] == "sub-123"
        refresh_card.assert_awaited_once()
        assert refresh_card.await_args.kwargs["submission_id"] == "sub-123"
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_record_separation_uses_tracker_identity_to_match_roster_personal_email() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "employee_name": "Alice Example",
        "employee_email": "",
        "personal_email": "alice@example.com",
        "job_category": "Teacher",
        "position": "Teacher",
    }
    roster.remove_employee_from_staff_roster.return_value = {"success": True}
    separations = AsyncMock()
    separations.add_separation_record.return_value = {"success": True, "action": "added"}
    tracker = AsyncMock()
    tracker.resolve_employee_relaxed.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }
    tracker.update_stage.return_value = {"success": True}

    mcp = FastMCP(name="test-separation-personal-email")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
        patch("onboarding_agent.integrations.card_state.mark_separation_action_complete", new=AsyncMock(return_value=None)),
        patch("onboarding_agent.integrations.card_state.refresh_separation_card", new=AsyncMock()),
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            job_title="Teacher",
            status_change="Separation",
            submission_id="sub-123",
        )

    assert result["success"] is True
    roster.find_employee_in_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        job_category="",
        personal_email="alice@example.com",
        position="Teacher",
    )
    separations.add_separation_record.assert_awaited_once()
    roster.remove_employee_from_staff_roster.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_separation_fails_when_staff_roster_row_is_not_found() -> None:
    from onboarding_agent.mcp_server.tools_separations import register

    roster = AsyncMock()
    roster.find_employee_in_staff_roster.return_value = {"found": False}
    roster._resolve_roster_match.return_value = {"found": False}
    separations = AsyncMock()
    tracker = AsyncMock()
    tracker.resolve_employee_relaxed.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }

    mcp = FastMCP(name="test-separation-roster-miss")
    register(mcp)

    with (
        patch("onboarding_agent.mcp_server.tools_separations._staff_roster", return_value=roster),
        patch("onboarding_agent.mcp_server.tools_separations._separations", return_value=separations),
        patch("onboarding_agent.mcp_server.tools_separations._tracker", return_value=tracker),
    ):
        tool_fn = await _get_tool_fn(mcp, "record_separation")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            job_title="Teacher",
            status_change="Separation",
            submission_id="sub-123",
        )

    assert result["success"] is False
    assert "No separation record was created" in result["error"]
    separations.add_separation_record.assert_not_awaited()
    roster.remove_employee_from_staff_roster.assert_not_awaited()


# ---------------------------------------------------------------------------
# tools_onboarding.get_onboarding_status
# ---------------------------------------------------------------------------

class TestGetOnboardingStatus:
    @pytest.fixture(autouse=True)
    def _patch_clients(self):
        self.tracker = AsyncMock()
        self.docusign = AsyncMock()
        self.docusign.find_latest_envelope_for_employee.return_value = {
            "found": False,
            "envelope_id": "",
            "status": "",
        }

        with (
            patch("onboarding_agent.mcp_server.tools_onboarding._tracker", return_value=self.tracker),
            patch("onboarding_agent.mcp_server.tools_onboarding._docusign", return_value=self.docusign),
        ):
            yield

    @pytest.mark.asyncio
    async def test_not_found_returns_found_false(self):
        self.tracker.find_employee_in_tracker.return_value = {"found": False}
        self.tracker.get_employee_stages.return_value = {"found": False}

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="nobody@example.com")

        assert result["found"] is False
        assert "No onboarding record found" in result["summary"]

    @pytest.mark.asyncio
    async def test_duplicate_email_returns_disambiguation_summary(self):
        self.tracker.get_employee_stages.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {
                    "row_id": "12",
                    "email": "mdoyle@example.com",
                    "location": "Bronx",
                    "job_title": "Teacher",
                    "added_to_tracker": "2026-04-01",
                },
                {
                    "row_id": "15",
                    "email": "mdoyle@example.com",
                    "location": "Queens",
                    "job_title": "Assistant Principal",
                    "added_to_tracker": "2026-04-02",
                },
            ],
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test-duplicate-status")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="mdoyle@example.com")

        assert result["found"] is False
        assert result["multiple_matches"] is True
        assert "Multiple onboarding records matched" in result["summary"]
        assert "location=Bronx" in result["summary"]
        assert "job_title=Assistant Principal" in result["summary"]

    @pytest.mark.asyncio
    async def test_get_onboarding_status_passes_submission_id(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True,
            "name": "Alice",
            "submission_id": "sub-123",
            "stages": {"Added to Tracker": "2026-04-01"},
        }
        self.docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
        self.docusign.find_latest_envelope_for_employee.return_value = {
            "found": False,
            "envelope_id": "",
            "status": "",
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test-status-submission-id")
        register(mcp)

        with patch("onboarding_agent.mcp_server.tools_onboarding.get_docusign_status_card", new=AsyncMock(return_value=None)):
            tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
            result = await tool_fn(employee_email="alice@example.com", submission_id="sub-123")

        self.tracker.get_employee_stages.assert_awaited_once_with(
            "alice@example.com",
            location="",
            job_title="",
            status_change="",
            submission_id="sub-123",
        )
        assert result["submission_id"] == "sub-123"

    @pytest.mark.asyncio
    async def test_found_with_draft_envelope(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "3", "name": "Alice",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "",
                "Sent Offer Letter": "",
                "Offer Letter Signed": "",
            },
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-123"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "created", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test2")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert result["docusign_status"] == "created"
        assert "draft has been created but not yet sent" in result["summary"]
        assert "Added to Staff Roster: pending" in result["summary"]

    @pytest.mark.asyncio
    async def test_found_with_completed_envelope(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "4", "name": "Bob",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "2026-04-02",
                "Sent Offer Letter": "2026-04-03",
                "Offer Letter Signed": "2026-04-04",
            },
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-456"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "completed", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test3")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="bob@example.com")

        assert result["docusign_status"] == "completed"
        assert "fully signed" in result["summary"]

    @pytest.mark.asyncio
    async def test_completed_envelope_reconciles_missing_signed_stage(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "5", "name": "Carol",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "2026-04-02",
                "Sent Offer Letter": "2026-04-03",
                "Offer Letter Signed": "",
            },
        }
        self.tracker.update_stage.return_value = {
            "success": True,
            "employee_email": "carol@example.com",
            "stage": "Offer Letter Signed",
            "value": "2026-04-04",
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": False, "envelope_id": ""
        }
        self.docusign.find_latest_envelope_for_employee.return_value = {
            "found": True, "envelope_id": "env-789", "status": "completed"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "completed", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test4")
        register(mcp)

        with (
            patch("onboarding_agent.mcp_server.tools_onboarding.get_docusign_status_card", new=AsyncMock(return_value=None)),
            patch("onboarding_agent.mcp_server.tools_onboarding.save_docusign_status_card", new=AsyncMock()),
            patch("onboarding_agent.integrations.teams.messenger.TeamsMessenger.send_channel_notification", new=AsyncMock(return_value={"success": True, "message_id": "msg-1"})),
        ):
            tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
            result = await tool_fn(employee_email="carol@example.com")

        self.tracker.update_stage.assert_awaited_once_with(
            "carol@example.com",
            "Offer Letter Signed",
            location="",
            job_title="",
            status_change="",
            submission_id="",
        )
        assert result["docusign_status"] == "completed"
        assert result["stages"]["Offer Letter Signed"] == "04/04/2026"


class TestDocuSignTools:
    @pytest.fixture(autouse=True)
    def _patch_clients(self):
        self.tracker = AsyncMock()
        self.docusign = AsyncMock()
        with (
            patch("onboarding_agent.mcp_server.tools_docusign._tracker", return_value=self.tracker),
            patch("onboarding_agent.mcp_server.tools_docusign._docusign", return_value=self.docusign),
        ):
            yield

    @pytest.mark.asyncio
    async def test_check_docusign_draft_exists_surfaces_duplicate_tracker_matches(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {"location": "Collier", "job_title": "Instructional Coach"},
                {"location": "Collier", "job_title": "Assistant Principal"},
            ],
        }
        self.tracker.get_employee_stages.side_effect = [
            {"found": True, "stages": {"Sent Offer Letter": ""}},
            {"found": True, "stages": {"Sent Offer Letter": ""}},
        ]

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "check_docusign_draft_exists")
        result = await tool_fn(employee_email="mdoyle@example.com")

        assert result["exists"] is False
        assert result["multiple_matches"] is True
        assert "Multiple tracker rows match this email" in result["error"]
        self.docusign.check_draft_exists.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_docusign_draft_exists_auto_resolves_single_unsent_match(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {
                    "location": "Collier",
                    "job_title": "Instructional Coach",
                    "status_change": "New Hire",
                },
                {
                    "location": "Collier",
                    "job_title": "Assistant Principal",
                    "status_change": "Promotion",
                },
            ],
        }
        self.tracker.get_employee_stages.side_effect = [
            {"found": True, "stages": {"Sent Offer Letter": ""}},
            {"found": True, "stages": {"Sent Offer Letter": "04/01/2026"}},
        ]
        self.docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-autoresolve")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "check_docusign_draft_exists")
        result = await tool_fn(employee_email="mdoyle@example.com")

        assert result["exists"] is True
        assert result["work_location"] == "Collier"
        assert result["job_title"] == "Instructional Coach"
        assert result["status_change"] == "New Hire"
        self.docusign.check_draft_exists.assert_awaited_once_with(
            "mdoyle@example.com",
            "Collier",
            "Instructional Coach",
            "New Hire",
        )

    @pytest.mark.asyncio
    async def test_check_docusign_draft_exists_uses_submission_id_to_refresh_tracker_fields(self):
        self.tracker.resolve_employee_relaxed.return_value = {
            "found": True,
            "email": "mdoyle@example.com",
            "submission_id": "sub-123",
            "location": "Collier",
            "job_title": "Content, Teacher I (Bachelor's Degree)",
            "status_change": "New Hire",
        }
        self.docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-check-from-submission-id")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "check_docusign_draft_exists")
        result = await tool_fn(
            employee_email="mdoyle@example.com",
            job_title="Teacher",
            submission_id="sub-123",
        )

        self.tracker.resolve_employee_relaxed.assert_awaited_once_with(
            "mdoyle@example.com",
            location="",
            job_title="Teacher",
            status_change="",
            submission_id="sub-123",
        )
        self.docusign.check_draft_exists.assert_awaited_once_with(
            "mdoyle@example.com",
            "Collier",
            "Content, Teacher I (Bachelor's Degree)",
            "New Hire",
        )
        assert result["job_title"] == "Content, Teacher I (Bachelor's Degree)"
        assert result["submission_id"] == "sub-123"

    @pytest.mark.asyncio
    async def test_create_offer_letter_draft_from_tracker_uses_submission_id_and_tracker_fields(self):
        self.tracker.resolve_employee_relaxed.return_value = {
            "found": True,
            "name": "Matt",
            "email": "mdoyle@example.com",
            "location": "Orange",
            "job_title": "Teacher",
            "status_change": "Transfer In",
            "start_date": "2026-04-10",
            "submission_id": "sub-123",
        }
        self.docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
        self.docusign.create_envelope_draft.return_value = {
            "success": True,
            "envelope_id": "env-789",
            "status": "created",
        }
        self.docusign.create_envelope_edit_view.return_value = {
            "success": True,
            "url": "https://review.example.com/env-789",
        }

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-create-from-tracker")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "create_offer_letter_draft_from_tracker")
        result = await tool_fn(
            employee_email="mdoyle@example.com",
            submission_id="sub-123",
        )

        assert result["success"] is True
        assert result["submission_id"] == "sub-123"
        assert result["start_date"] == "2026-04-10"
        assert result["review_url"] == "https://review.example.com/env-789"
        self.tracker.resolve_employee_relaxed.assert_awaited_once_with(
            "mdoyle@example.com",
            location="",
            job_title="",
            status_change="",
            submission_id="sub-123",
        )
        self.docusign.create_envelope_draft.assert_awaited_once_with(
            employee_name="Matt",
            employee_email="mdoyle@example.com",
            start_date="2026-04-10",
            position="Teacher",
            work_location="Orange",
            status_change="Transfer In",
            submission_id="sub-123",
        )

    @pytest.mark.asyncio
    async def test_delete_offer_letter_draft_from_tracker_prefers_submission_id(self):
        self.tracker.resolve_employee_relaxed.return_value = {
            "found": True,
            "name": "Matt",
            "email": "mdoyle@example.com",
            "location": "Orange",
            "job_title": "Teacher",
            "status_change": "Transfer In",
            "submission_id": "sub-123",
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True,
            "envelope_id": "env-123",
            "status": "created",
        }
        self.docusign.delete_draft_envelope.return_value = {
            "success": True,
            "envelope_id": "env-123",
            "status": "deleted",
        }

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-delete-from-tracker")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "delete_offer_letter_draft_from_tracker")
        result = await tool_fn(
            employee_email="mdoyle@example.com",
            submission_id="sub-123",
        )

        self.tracker.resolve_employee_relaxed.assert_awaited_once_with(
            "mdoyle@example.com",
            location="",
            job_title="",
            status_change="",
            submission_id="sub-123",
        )
        self.docusign.check_draft_exists.assert_awaited_once_with(
            "mdoyle@example.com",
            "Orange",
            "Teacher",
            "Transfer In",
        )
        self.docusign.delete_draft_envelope.assert_awaited_once_with("env-123")
        assert result["success"] is True
        assert result["status"] == "deleted"
        assert result["submission_id"] == "sub-123"

    @pytest.mark.asyncio
    async def test_list_docusign_drafts_returns_preview_and_total(self):
        self.docusign.list_draft_envelopes.return_value = {
            "drafts": [
                {
                    "envelope_id": "env-1",
                    "employee_email": "alice@example.com",
                    "employee_name": "Alice Example",
                    "work_location": "Bronx",
                    "job_title": "Teacher",
                    "status_change": "New Hire",
                    "created_date_time": "2026-04-03T20:00:00Z",
                }
            ],
            "total_count": 7,
        }

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-list-drafts")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "list_docusign_drafts")
        result = await tool_fn(limit=5)

        self.docusign.list_draft_envelopes.assert_awaited_once_with(
            employee_email="",
            work_location="",
            job_title="",
            status_change="",
            limit=5,
        )
        assert result["total_count"] == 7
        assert len(result["drafts"]) == 1
        assert "Found 7 DocuSign draft(s)" in result["summary"]

    @pytest.mark.asyncio
    async def test_delete_docusign_draft_by_envelope_id_bypasses_tracker(self):
        self.docusign.delete_draft_envelope.return_value = {
            "success": True,
            "envelope_id": "env-123",
            "employee_email": "alice@example.com",
            "work_location": "Bronx",
            "job_title": "Teacher",
            "status_change": "New Hire",
            "status": "deleted",
        }

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-delete-direct")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "delete_docusign_draft")
        result = await tool_fn(envelope_id="env-123")

        self.docusign.delete_draft_envelope.assert_awaited_once_with("env-123")
        self.tracker.find_employee_in_tracker.assert_not_awaited()
        assert result["success"] is True
        assert result["status"] == "deleted"


class TestTrackerTools:
    @pytest.fixture(autouse=True)
    def _patch_tracker(self):
        self.tracker = AsyncMock()
        with patch("onboarding_agent.mcp_server.tools_tracker._tracker", return_value=self.tracker):
            yield

    @pytest.mark.asyncio
    async def test_find_employee_in_tracker_returns_compact_payload(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "row_id": "12",
            "name": "Alice Example",
            "email": "alice@example.com",
            "location": "Bronx",
            "start_date": "2026-04-01",
            "position": "HR",
            "manager_email": "manager@example.com",
            "staff_phone": "555-111-2222",
            "compensation": "60000",
            "status": "Sent Offer Letter",
            "stages": {
                "Added to Tracker": "2026-03-01",
                "Sent Offer Letter": "2026-03-02",
            },
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "find_employee_in_tracker")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert result["email"] == "alice@example.com"
        assert result["status"] == "Sent Offer Letter"
        assert "staff_phone" not in result
        assert "compensation" not in result
        assert "stages" not in result
        assert "Alice Example" in result["summary"]

    @pytest.mark.asyncio
    async def test_update_employee_in_tracker_passes_field_updates(self):
        self.tracker.update_employee_in_tracker.return_value = {
            "success": True,
            "row_id": "12",
            "updated_fields": ["job_title", "work_location"],
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-update-row-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_employee_in_tracker")
        result = await tool_fn(
            employee_email="alice@example.com",
            location="Bronx",
            current_job_title="Teacher",
            current_status_change="New Hire",
            job_title="Assistant Principal",
            work_location="Queens",
            compensation="80000",
        )

        assert result["success"] is True
        self.tracker.update_employee_in_tracker.assert_awaited_once_with(
            "alice@example.com",
            location="Bronx",
            current_job_title="Teacher",
            current_status_change="New Hire",
            submission_id="",
            staff_name=None,
            staff_email=None,
            requested_start_date=None,
            job_title="Assistant Principal",
            work_location="Queens",
            requesting_manager=None,
            status_change=None,
            staff_phone=None,
            education_level=None,
            supplements=None,
            license_number=None,
            uploaded_credentials=None,
            compensation="80000",
            employment_type=None,
            contract_term=None,
        )

    @pytest.mark.asyncio
    async def test_list_employees_returns_capped_preview(self):
        employees = []
        for index in range(30):
            employees.append(
                {
                    "name": f"Employee {index}",
                    "email": f"user{index}@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "stages": {"Added to Tracker": "2026-04-01"},
                }
            )
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": employees,
            "count": len(employees),
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-list-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")
        result = await tool_fn(recent_days=0)

        assert result["count"] == 30
        assert result["returned_count"] == 25
        assert result["truncated"] is True
        assert len(result["employees"]) == 25
        assert result["employees"][0]["email"] == "user0@example.com"
        assert "and 5 more" in result["summary"]

    @pytest.mark.asyncio
    async def test_list_employees_defaults_to_recent_30_days(self):
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": [
                {
                    "name": "Recent Hire",
                    "email": "recent@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-03-20",
                    "stages": {"Added to Tracker": "2026-03-20"},
                },
                {
                    "name": "Older Hire",
                    "email": "older@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-01-15",
                    "stages": {"Added to Tracker": "2026-01-15"},
                },
            ],
            "count": 2,
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-recent-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")

        with patch("onboarding_agent.mcp_server.tools_tracker.date") as mock_date:
            from datetime import date as real_date
            mock_date.today.return_value = real_date(2026, 3, 31)
            mock_date.side_effect = real_date
            result = await tool_fn()

        assert result["count"] == 1
        assert result["employees"][0]["email"] == "recent@example.com"
        assert result["recent_days"] == 30

    @pytest.mark.asyncio
    async def test_list_employees_supports_optional_filters(self):
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": [
                {
                    "name": "Bronx Ops",
                    "email": "bronx.ops@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-03-20",
                    "stages": {"Added to Tracker": "2026-03-20"},
                },
                {
                    "name": "Queens HR",
                    "email": "queens.hr@example.com",
                    "location": "Queens",
                    "position": "HR",
                    "start_date": "2026-03-21",
                    "stages": {"Added to Tracker": "2026-03-21"},
                },
            ],
            "count": 2,
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-filter-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")
        result = await tool_fn(location="Bronx", position="Ops", recent_days=0)

        assert result["count"] == 1
        assert result["employees"][0]["email"] == "bronx.ops@example.com"
        assert result["location"] == "Bronx"
        assert result["position"] == "Ops"

    @pytest.mark.asyncio
    async def test_update_tracker_stage_passes_explicit_stage_value(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {"Background Cleared": ""},
        }
        self.tracker.update_stage.return_value = {"success": True, "value": "2026-04-02"}

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-update-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="Background Cleared",
            stage_value="2026-04-02",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
        )

        assert result["success"] is True
        self.tracker.update_stage.assert_awaited_once_with(
            "alice@example.com",
            "Background Cleared",
            value="2026-04-02",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            submission_id="",
        )

    @pytest.mark.asyncio
    async def test_update_tracker_stage_resolves_relaxed_stage_name(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {"Background Submission": ""},
        }
        self.tracker.update_stage.return_value = {"success": True, "value": "2026-04-02"}

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-update-relaxed-stage-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="background submit",
            stage_value="2026-04-02",
        )

        assert result["success"] is True
        self.tracker.update_stage.assert_awaited_once_with(
            "alice@example.com",
            "Background Submission",
            value="2026-04-02",
            location="",
            job_title="",
            status_change="",
            submission_id="",
        )

    @pytest.mark.asyncio
    async def test_update_tracker_stage_sends_clear_to_start_email_with_cc(self):
        self.tracker.find_employee_in_tracker.side_effect = [
            {
                "found": True,
                "email": "alice@example.com",
                "stages": {"Clear to Start": ""},
            },
            {
                "found": True,
                "email": "alice@example.com",
                "name": "Alice Example",
                "requested_start_date": "2026-08-03",
                "location": "Collier",
                "job_title": "Teacher",
                "requesting_manager": "Morgan Manager",
                "stages": {"Clear to Start": "2026-04-14"},
            },
        ]
        self.tracker.update_stage.return_value = {"success": True, "value": "2026-04-14"}

        from onboarding_agent.mcp_server.tools_tracker import register

        send_clear_to_start = AsyncMock(return_value={"success": True, "cc_emails": ["manager@example.com"]})
        mcp = FastMCP(name="tracker-clear-to-start-email-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        with patch(
            "onboarding_agent.mcp_server.tools_email.send_clear_to_start_email",
            new=send_clear_to_start,
        ):
            result = await tool_fn(
                employee_email="alice@example.com",
                stage_name="Clear to Start",
                location="Collier",
                job_title="Teacher",
                status_change="New Hire",
                cc_emails="ops@example.com",
                treasurer_name="Taylor Treasurer",
                treasurer_email="treasurer@example.com",
                hiring_manager_email="manager@example.com",
            )

        assert result["success"] is True
        assert result["clear_to_start_email"]["success"] is True
        send_clear_to_start.assert_awaited_once_with(
            "alice@example.com",
            "Alice Example",
            requested_start_date="2026-04-14",
            treasurer_name="Taylor Treasurer",
            treasurer_email="treasurer@example.com",
            hiring_manager_name="Morgan Manager",
            hiring_manager_email="manager@example.com",
            cc_emails="ops@example.com",
        )

    @pytest.mark.asyncio
    async def test_update_tracker_stage_requires_clear_to_start_email_fields(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {"Clear to Start": ""},
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-clear-to-start-missing-email-fields-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="Clear to Start",
        )

        assert result["success"] is False
        assert result["needs_clarification"] is True
        assert result["missing_fields"] == [
            "treasurer_name",
            "treasurer_email",
            "hiring_manager_email",
        ]
        self.tracker.update_stage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tracker_stage_returns_clarification_for_unknown_stage(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {},
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-update-unknown-stage-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="paperwork started",
        )

        assert result["success"] is False
        assert result["needs_clarification"] is True
        self.tracker.find_employee_in_tracker.assert_not_awaited()
        self.tracker.update_stage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tracker_stage_surfaces_lookup_ambiguity(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {"location": "Collier", "job_title": "Teacher"},
                {"location": "Collier", "job_title": "Coach"},
            ],
            "error": "Multiple tracker rows matched this email.",
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-update-ambiguity-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="ncruz@example.com",
            stage_name="Background Submission",
        )

        assert result["success"] is False
        assert result["multiple_matches"] is True
        assert len(result["matches"]) == 2
        self.tracker.update_stage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_find_employee_in_tracker_passes_submission_id(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "row_id": "12",
            "name": "Alice Example",
            "email": "alice@example.com",
            "submission_id": "sub-123",
            "location": "Bronx",
            "stages": {},
            "status": "Added to Tracker",
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-submission-id-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "find_employee_in_tracker")
        result = await tool_fn(employee_email="alice@example.com", submission_id="sub-123")

        self.tracker.find_employee_in_tracker.assert_awaited_once_with(
            "alice@example.com",
            location="",
            job_title="",
            status_change="",
            submission_id="sub-123",
        )
        assert result["submission_id"] == "sub-123"

    @pytest.mark.asyncio
    async def test_clear_tracker_stage_clears_value(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {"Background Submission": ""},
        }
        self.tracker.update_stage.return_value = {"success": True, "value": ""}

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-clear-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "clear_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="Background Submission",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
        )

        assert result["success"] is True
        self.tracker.update_stage.assert_awaited_once_with(
            "alice@example.com",
            "Background Submission",
            value="",
            location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            submission_id="",
        )

    @pytest.mark.asyncio
    async def test_clear_tracker_stage_resolves_relaxed_stage_name(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "alice@example.com",
            "stages": {"Background Submission": ""},
        }
        self.tracker.update_stage.return_value = {"success": True, "value": ""}

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-clear-relaxed-stage-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "clear_tracker_stage")
        result = await tool_fn(
            employee_email="alice@example.com",
            stage_name="background submit",
        )

        assert result["success"] is True
        self.tracker.update_stage.assert_awaited_once_with(
            "alice@example.com",
            "Background Submission",
            value="",
            location="",
            job_title="",
            status_change="",
            submission_id="",
        )

    @pytest.mark.asyncio
    async def test_get_employee_stages_summary_includes_all_tracker_stages(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "row_id": "12",
            "name": "Alice Example",
            "email": "alice@example.com",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Background Submission": "2026-04-02",
                "Background Cleared": "",
                "Added to ADP": "",
                "Employee Complete ADP Profile": "",
                "Complete in ADP": "",
                "Proration": "",
                "Clear to Start": "",
                "Drug Screening": "",
            },
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-stages-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "get_employee_stages")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert "Background Submission: 04/02/2026" in result["summary"]
        assert "Background Cleared: pending" in result["summary"]
        assert "Clear to Start: pending" in result["summary"]

    @pytest.mark.asyncio
    async def test_update_tracker_stage_rejects_inactive_na_stage(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "row_id": "12",
            "name": "Matt",
            "email": "mdoyle@example.com",
            "stages": {
                "Drug Screening": "N/A",
            },
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-inactive-stage-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "update_tracker_stage")
        result = await tool_fn(
            employee_email="mdoyle@example.com",
            stage_name="Drug Screening",
        )

        assert result["success"] is False
        assert result["inactive"] is True
        assert "inactive/non-applicable" in result["error"]
        self.tracker.update_stage.assert_not_awaited()
