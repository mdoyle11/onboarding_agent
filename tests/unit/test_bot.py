from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from onboarding_agent.integrations.teams.bot import (
    _apply_card_side_effects_from_tool_results,
    _refresh_cards_from_session_context,
    _refresh_draft_result_surfaces,
    _run_deterministic_card_action_in_background,
    _should_refresh_cards,
)


def test_should_refresh_cards_only_for_relevant_tool_results() -> None:
    assert _should_refresh_cards([HumanMessage(content="hello")]) is False
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="get_onboarding_status"),
    ]) is True
    assert _should_refresh_cards([
        ToolMessage(content='{"success": true}', tool_call_id="1", name="send_onboarding_email"),
    ]) is False


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
