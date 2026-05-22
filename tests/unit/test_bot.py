from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from onboarding_agent.integrations.teams.bot import (
    _apply_card_side_effects_from_tool_results,
    _expand_slash_command,
    _parse_clear_to_start_command,
    _refresh_cards_from_session_context,
    _refresh_draft_result_surfaces,
    _run_deterministic_card_action_in_background,
    _send_clear_to_start_card_from_command,
    _should_refresh_cards,
)
from onboarding_agent.integrations.teams.card_actions import handle_clear_to_start_card_action


def test_should_refresh_cards_only_for_relevant_tool_results() -> None:
    assert _should_refresh_cards([HumanMessage(content="hello")]) is False
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="get_onboarding_status"),
    ]) is True
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="send_onboarding_email"),
    ]) is False
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="update_tracker_field"),
    ]) is True
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="update_staff_roster_field"),
    ]) is True


def test_expand_slash_command_returns_help_text() -> None:
    handled, text = _expand_slash_command("/help")

    assert handled is True
    assert "**Onboarding Agent Help**" in text
    assert "**Status And Lookup**" in text
    assert "**Staff Roster**" in text
    assert "**Natural Language Examples**" in text
    assert "*Examples*" in text
    assert "/status <email>" in text
    assert "- `/status employee@example.com`" in text
    assert '`/drafts`' in text
    assert "/clear-to-start <email> [submission_id]" in text


def test_expand_slash_command_translates_status_to_agent_prompt() -> None:
    handled, text = _expand_slash_command("/status employee@example.com")

    assert handled is False
    assert text == "Get onboarding status for employee@example.com."


def test_expand_slash_command_translates_find_tracker() -> None:
    handled, text = _expand_slash_command("/find-tracker employee@example.com")

    assert handled is False
    assert text == "Find employee@example.com in the onboarding tracker."


def test_expand_slash_command_translates_capacity_with_multi_word_group() -> None:
    handled, text = _expand_slash_command('/capacity Collier "Support Staff"')

    assert handled is False
    assert text == "Check staff roster capacity at Collier for group Support Staff."


def test_expand_slash_command_reports_usage_when_required_args_missing() -> None:
    handled, text = _expand_slash_command("/vacancies")

    assert handled is True
    assert text == "Usage: /vacancies <location>"


def test_expand_slash_command_translates_drafts() -> None:
    handled, text = _expand_slash_command("/drafts")

    assert handled is False
    assert text == "List unsent DocuSign drafts waiting to be sent."


def test_expand_slash_command_translates_leave_start() -> None:
    handled, text = _expand_slash_command("/leave employee@example.com start")

    assert handled is False
    assert text == "Update staff roster leave status for employee@example.com to On Leave."


def test_expand_slash_command_translates_leave_end() -> None:
    handled, text = _expand_slash_command("/leave employee@example.com end")

    assert handled is False
    assert text == "Update staff roster leave status for employee@example.com to Active."


def test_expand_slash_command_translates_clear_stage() -> None:
    handled, text = _expand_slash_command('/clear-stage employee@example.com "Background Submission"')

    assert handled is False
    assert text == "Clear tracker stage 'Background Submission' for employee@example.com so it is blank."


def test_expand_slash_command_translates_update_tracker_field() -> None:
    handled, text = _expand_slash_command('/update-field tracker employee@example.com "Requested Start Date" "2026-08-03"')

    assert handled is False
    assert text == "Use update_tracker_field to update the tracker field 'Requested Start Date' for employee@example.com to '2026-08-03'. This is not a tracker stage update."


def test_expand_slash_command_translates_update_roster_field() -> None:
    handled, text = _expand_slash_command('/update-field roster employee@example.com "Grade Level" "3"')

    assert handled is False
    assert text == "Use update_staff_roster_field to update the roster field 'Grade Level' for employee@example.com to '3'. This is not a tracker stage update."


def test_expand_slash_command_translates_update_stage_complete() -> None:
    handled, text = _expand_slash_command('/update-stage employee@example.com "Background Submission" complete')

    assert handled is False
    assert text == "Mark tracker stage 'Background Submission' complete for employee@example.com."


def test_expand_slash_command_translates_update_stage_incomplete() -> None:
    handled, text = _expand_slash_command('/update-stage employee@example.com "Background Submission" incomplete')

    assert handled is False
    assert text == "Clear tracker stage 'Background Submission' for employee@example.com so it is blank."


def test_parse_clear_to_start_command() -> None:
    handled, args, usage = _parse_clear_to_start_command("/clear-to-start employee@example.com sub-123")

    assert handled is True
    assert args == ["employee@example.com", "sub-123"]
    assert usage == ""


def test_parse_clear_to_start_command_accepts_submission_id_words() -> None:
    handled, args, usage = _parse_clear_to_start_command(
        "/clear-to-start employee@example.com submission id 163"
    )

    assert handled is True
    assert args == ["employee@example.com", "163"]
    assert usage == ""


def test_parse_clear_to_start_command_reports_usage() -> None:
    handled, args, usage = _parse_clear_to_start_command("/clear-to-start")

    assert handled is True
    assert args == []
    assert usage == "Usage: /clear-to-start <email> [submission_id]"


@pytest.mark.asyncio
async def test_send_clear_to_start_card_from_command_rejects_partial_email() -> None:
    result = await _send_clear_to_start_card_from_command(AsyncMock(), ["mdoyle@bridgeprepacademy"])

    assert result == (
        "Clear-to-start requires the employee's full email address. "
        "Received `mdoyle@bridgeprepacademy`."
    )


def test_expand_slash_command_rejects_unknown_update_field_target() -> None:
    handled, text = _expand_slash_command("/update-field sheet employee@example.com Field Value")

    assert handled is True
    assert text == "Usage: /update-field <tracker|roster> <email> <column> <value>"


@pytest.mark.asyncio
async def test_refresh_cards_from_session_context_uses_identity_fields() -> None:
    refresh_new_hire = AsyncMock(return_value={"success": True})
    refresh_docusign = AsyncMock(return_value={"success": False, "error": "missing"})

    with (
        patch("onboarding_agent.integrations.teams.bot.refresh_new_hire_card", new=refresh_new_hire),
        patch("onboarding_agent.integrations.teams.bot.refresh_docusign_status_card", new=refresh_docusign),
    ):
        await _refresh_cards_from_session_context(
            {
                "employee_email": "alice@example.com",
                "work_location": "Bronx",
                "job_title": "Teacher",
                "status_change": "New Hire",
            }
        )

    identity = refresh_new_hire.await_args.args[0]
    assert identity.email == "alice@example.com"
    assert identity.work_location == "Bronx"
    assert identity.job_title == "Teacher"
    assert identity.status_change == "New Hire"
    assert refresh_new_hire.await_args.kwargs["submission_id"] == ""
    refresh_docusign.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_cards_from_session_context_passes_submission_id() -> None:
    refresh_new_hire = AsyncMock(return_value={"success": True})
    refresh_docusign = AsyncMock(return_value={"success": True})

    with (
        patch("onboarding_agent.integrations.teams.bot.refresh_new_hire_card", new=refresh_new_hire),
        patch("onboarding_agent.integrations.teams.bot.refresh_docusign_status_card", new=refresh_docusign),
    ):
        await _refresh_cards_from_session_context(
            {
                "submission_id": "sub-123",
                "employee_email": "alice@example.com",
                "work_location": "Bronx",
                "job_title": "Teacher",
                "status_change": "New Hire",
            }
        )

    assert refresh_new_hire.await_args.kwargs["submission_id"] == "sub-123"
    assert refresh_docusign.await_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_apply_card_side_effects_marks_offer_letter_draft_complete() -> None:
    mark_complete = AsyncMock(return_value={})

    with patch("onboarding_agent.integrations.teams.bot.mark_new_hire_action_complete", new=mark_complete):
        await _apply_card_side_effects_from_tool_results([
            ToolMessage(
                content=(
                    '{"success": true, "employee_email": "alice@example.com", '
                    '"work_location": "Bronx", "job_title": "Teacher", "status_change": "New Hire", '
                    '"submission_id": "sub-123"}'
                ),
                tool_call_id="1",
                name="create_offer_letter_draft_from_tracker",
            )
        ])

    identity = mark_complete.await_args.args[0]
    assert identity.email == "alice@example.com"
    assert identity.work_location == "Bronx"
    assert identity.job_title == "Teacher"
    assert identity.status_change == "New Hire"
    assert mark_complete.await_args.args[1] == "create_docusign_draft"
    assert mark_complete.await_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_apply_card_side_effects_clears_offer_letter_draft_completion_on_delete() -> None:
    clear_complete = AsyncMock(return_value={})
    delete_card = AsyncMock(return_value=True)

    with (
        patch("onboarding_agent.integrations.teams.bot.clear_new_hire_action_complete", new=clear_complete),
        patch("onboarding_agent.integrations.teams.bot.delete_docusign_status_card", new=delete_card),
    ):
        await _apply_card_side_effects_from_tool_results([
            ToolMessage(
                content=(
                    '{"success": true, "employee_email": "alice@example.com", '
                    '"work_location": "Bronx", "job_title": "Teacher", "status_change": "New Hire", '
                    '"submission_id": "sub-123"}'
                ),
                tool_call_id="1",
                name="delete_offer_letter_draft_from_tracker",
            )
        ])

    identity = clear_complete.await_args.args[0]
    assert identity.email == "alice@example.com"
    assert clear_complete.await_args.args[1] == "create_docusign_draft"
    assert clear_complete.await_args.kwargs["submission_id"] == "sub-123"
    assert delete_card.await_args.args[0].email == "alice@example.com"
    assert delete_card.await_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_refresh_draft_result_surfaces_prefers_docusign_card() -> None:
    refresh_new_hire = AsyncMock(return_value={"success": True})
    refresh_docusign = AsyncMock(return_value={"success": True})

    with (
        patch("onboarding_agent.integrations.teams.bot.refresh_new_hire_card", new=refresh_new_hire),
        patch("onboarding_agent.integrations.teams.bot.refresh_docusign_status_card", new=refresh_docusign),
    ):
        await _refresh_draft_result_surfaces(
            {
                "employee_email": "alice@example.com",
                "submission_id": "sub-123",
                "work_location": "Bronx",
                "job_title": "Teacher",
                "status_change": "New Hire",
            }
        )

    refresh_docusign.assert_awaited_once()
    refresh_new_hire.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_draft_action_suppresses_failure_when_completion_can_be_reconfirmed() -> None:
    with (
        patch(
            "onboarding_agent.integrations.teams.bot.execute_new_hire_card_action_without_context",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "onboarding_agent.integrations.teams.bot.card_action_already_completed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "onboarding_agent.integrations.teams.bot._refresh_draft_result_surfaces",
            new=AsyncMock(),
        ) as refresh_surfaces,
        patch("onboarding_agent.integrations.teams.bot.notify_card_action_failure", new=AsyncMock()) as notify_failure,
    ):
        await _run_deterministic_card_action_in_background(
            card_action={
                "action": "create_docusign_draft",
                "employee_email": "alice@example.com",
                "submission_id": "sub-123",
                "work_location": "Bronx",
                "job_title": "Teacher",
                "status_change": "New Hire",
            }
        )

    refresh_surfaces.assert_awaited_once()
    notify_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_to_start_card_action_uses_form_inputs() -> None:
    context = AsyncMock()
    context.activity.reply_to_id = "msg-1"
    update_stage = AsyncMock(return_value={
        "success": True,
        "clear_to_start_email": {"success": True},
    })

    with patch("onboarding_agent.mcp_server.tools_tracker.update_tracker_stage_for_employee", new=update_stage):
        await handle_clear_to_start_card_action(
            context,
            {
                "action": "send_clear_to_start",
                "employee_email": "alice@example.com",
                "submission_id": "sub-123",
                "work_location": "Collier",
                "job_title": "Teacher",
                "status_change": "New Hire",
                "clear_to_start_date": "2026-08-03",
                "treasurer_name": "Taylor Treasurer",
                "treasurer_email": "treasurer@example.com",
                "hiring_manager_email": "manager@example.com",
                "cc_emails": "ops@example.com",
                "message_id": "msg-1",
            },
        )

    update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Clear to Start",
        stage_value="2026-08-03",
        location="Collier",
        job_title="Teacher",
        status_change="New Hire",
        submission_id="sub-123",
        cc_emails="ops@example.com",
        treasurer_name="Taylor Treasurer",
        treasurer_email="treasurer@example.com",
        hiring_manager_email="manager@example.com",
    )
    context.update_activity.assert_awaited_once()
    context.send_activity.assert_awaited_once()
