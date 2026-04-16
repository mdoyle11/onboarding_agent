"""Tests for queued job handling."""

from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.runtime.job_queue import QueueJob
from onboarding_agent.runtime.jobs import (
    JOB_DOCUSIGN,
    JOB_NEW_HIRE,
    process_job,
)


@pytest.mark.asyncio
async def test_process_new_hire_job_normalizes_uploaded_credentials_links() -> None:
    payload = {
        "submissionId": "sub-123",
        "staffName": "Alice Example",
        "staffEmail": "alice@example.com",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
        "statusChange": "New Hire",
        "uploadedCredentials": (
            '[{"name":"Credential.pdf","link":"https://example.com/doc.pdf","id":"123"}]'
        ),
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": False}
    tracker.add_employee_to_tracker.return_value = {"success": True, "row_id": "10"}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    kwargs = tracker.add_employee_to_tracker.await_args.kwargs
    assert kwargs["submission_id"] == "sub-123"
    assert kwargs["uploaded_credentials"] == "https://example.com/doc.pdf"


@pytest.mark.asyncio
async def test_process_new_hire_job_formats_multiple_uploaded_credential_links_single_line() -> None:
    payload = {
        "staffName": "Alice Example",
        "staffEmail": "alice@example.com",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
        "statusChange": "New Hire",
        "uploadedCredentials": (
            '[{"name":"A.pdf","link":"https://example.com/a.pdf"},'
            '{"name":"B.pdf","link":"https://example.com/b.pdf"}]'
        ),
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": False}
    tracker.add_employee_to_tracker.return_value = {"success": True, "row_id": "10"}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    kwargs = tracker.add_employee_to_tracker.await_args.kwargs
    assert kwargs["uploaded_credentials"] == "https://example.com/a.pdf https://example.com/b.pdf"


@pytest.mark.asyncio
async def test_process_new_hire_job_passes_submission_id_into_new_hire_card_payload() -> None:
    payload = {
        "submissionId": "sub-123",
        "staffName": "Alice Example",
        "staffEmail": "alice@example.com",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
        "statusChange": "New Hire",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": False}
    tracker.add_employee_to_tracker.return_value = {"success": True, "row_id": "10"}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": False, "envelope_id": ""}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
        patch("onboarding_agent.integrations.adaptive_cards.new_hire_card", return_value={"type": "AdaptiveCard"}) as build_card,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    assert build_card.call_count == 1
    assert build_card.call_args.kwargs["submission_id"] == "sub-123"


@pytest.mark.asyncio
async def test_process_job_invokes_agent_for_new_hire() -> None:
    mock_process = AsyncMock(return_value=None)
    payload = {"employeeEmail": "alice@example.com"}

    with patch("onboarding_agent.runtime.jobs.process_new_hire_job", mock_process):
        await process_job(QueueJob(job_type=JOB_NEW_HIRE, payload=payload))

    mock_process.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_process_job_invokes_agent_for_docusign() -> None:
    mock_process = AsyncMock(return_value=None)
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }

    with patch("onboarding_agent.runtime.jobs.process_docusign_job", mock_process):
        await process_job(QueueJob(job_type=JOB_DOCUSIGN, payload=payload))

    mock_process.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_process_docusign_job_uses_composite_identity_for_stage_updates() -> None:
    payload = {
        "envelope_id": "env-123",
        "status": "sent",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "submission_id": "sub-123",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}
    docusign = AsyncMock()

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
    ):
        from onboarding_agent.runtime.jobs import process_docusign_job

        await process_docusign_job(payload)

    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Sent Offer Letter",
        location="Bronx",
        job_title="Teacher",
        status_change="",
        submission_id="sub-123",
    )


@pytest.mark.asyncio
async def test_process_docusign_job_preserves_existing_staff_roster_state_on_completed_card() -> None:
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
        "submission_id": "sub-123",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}
    docusign = AsyncMock()
    staff_roster = AsyncMock()
    staff_roster.find_employee_in_staff_roster.return_value = {
        "found": True,
        "job_category": "Teacher",
    }

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.StaffRosterClient", return_value=staff_roster),
        patch("onboarding_agent.runtime.jobs.save_docusign_status_card", new=AsyncMock()) as save_card,
    ):
        from onboarding_agent.runtime.jobs import process_docusign_job

        await process_docusign_job(payload)

    staff_roster.find_employee_in_staff_roster.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        personal_email="alice@example.com",
        employee_name="Alice Example",
        position="Teacher",
    )
    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Offer Letter Signed",
        location="Bronx",
        job_title="Teacher",
        status_change="New Hire",
        submission_id="sub-123",
    )
    tracker.find_employee_in_tracker.assert_awaited_once_with(
        "alice@example.com",
        location="Bronx",
        job_title="Teacher",
        status_change="New Hire",
        submission_id="sub-123",
    )
    sent_card = teams.send_channel_notification.await_args.kwargs["card"]
    add_action = next(action for action in sent_card["actions"] if action.get("title") == "\u2713 Added To Staff Roster")
    assert add_action["isEnabled"] is False
    job_category_input = next(block for block in sent_card["body"] if block.get("id") == "job_category")
    assert job_category_input["value"] == "Teacher"
    save_kwargs = save_card.await_args.kwargs
    assert save_kwargs["roster_added"] is True
    assert save_kwargs["job_category"] == "Teacher"


@pytest.mark.asyncio
async def test_process_docusign_completed_posts_top_level_when_existing_card_is_draft_thread() -> None:
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
        "work_location": "Bronx",
        "job_title": "Teacher",
        "status_change": "New Hire",
        "submission_id": "sub-123",
    }
    tracker = AsyncMock()
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    tracker.find_employee_in_tracker.return_value = {
        "found": True,
        "name": "Alice Example",
        "position": "Teacher",
        "job_title": "Teacher",
    }
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "signed-msg"}
    docusign = AsyncMock()
    staff_roster = AsyncMock()
    staff_roster.find_employee_in_staff_roster.return_value = {"found": False}
    existing_draft_thread_card = {
        "message_id": "draft-thread-reply-msg",
        "status": "created",
    }

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.StaffRosterClient", return_value=staff_roster),
        patch("onboarding_agent.runtime.jobs._card_state_available", return_value=True),
        patch("onboarding_agent.runtime.jobs.get_docusign_status_card", new=AsyncMock(return_value=existing_draft_thread_card)),
        patch("onboarding_agent.runtime.jobs.update_proactive_card", new=AsyncMock()) as update_card,
        patch("onboarding_agent.runtime.jobs.save_docusign_status_card", new=AsyncMock()) as save_card,
    ):
        from onboarding_agent.runtime.jobs import process_docusign_job

        await process_docusign_job(payload)

    update_card.assert_not_awaited()
    teams.send_channel_notification.assert_awaited_once()
    assert "reply_to_id" not in teams.send_channel_notification.await_args.kwargs
    assert save_card.await_args.kwargs["message_id"] == "signed-msg"
    assert save_card.await_args.kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_process_background_clearance_job_uses_composite_identity_for_stage_updates() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True, "name": "Alice Example"}
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch(
            "onboarding_agent.mcp_server.tools_email.send_background_clearance_confirmation_email",
            new=AsyncMock(return_value={"success": True}),
        ),
    ):
        from onboarding_agent.runtime.jobs import process_background_clearance_job

        await process_background_clearance_job(payload)

    tracker.update_stage.assert_awaited_once_with(
        "alice@example.com",
        "Background Submission",
        location="Bronx",
        job_title="Teacher",
        status_change="",
    )


@pytest.mark.asyncio
async def test_process_background_clearance_job_does_not_raise_when_confirmation_email_fails() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True, "name": "Alice Example"}
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch(
            "onboarding_agent.mcp_server.tools_email.send_background_clearance_confirmation_email",
            new=AsyncMock(return_value={"success": False, "error": "invalid recipient"}),
        ),
    ):
        from onboarding_agent.runtime.jobs import process_background_clearance_job

        await process_background_clearance_job(payload)


@pytest.mark.asyncio
async def test_process_background_clearance_job_prefers_tracker_name_for_confirmation_email() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True, "name": "Alice Example"}
    tracker.update_stage.return_value = {"success": True, "value": "2026-04-01"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}
    send_confirmation = AsyncMock(return_value={"success": True})

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch(
            "onboarding_agent.mcp_server.tools_email.send_background_clearance_confirmation_email",
            new=send_confirmation,
        ),
    ):
        from onboarding_agent.runtime.jobs import process_background_clearance_job

        await process_background_clearance_job(payload)

    send_confirmation.assert_awaited_once_with("alice@example.com", "Alice Example")


@pytest.mark.asyncio
async def test_process_new_hire_job_passes_extended_fields_to_tracker() -> None:
    payload = {
        "staffName": "Alice Example",
        "staffEmail": "alice@example.com",
        "requestedStartDate": "2026-04-01",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "requestingManager": "manager@example.com",
        "statusChange": "New hire",
        "staffPhone": "555-0000",
        "educationLevel": "Bachelors",
        "supplements": "None",
        "licenseNumber": "LIC-123",
        "uploadedCredentials": "Yes",
        "compensation": "65000",
        "employmentType": "Full-time",
        "contractTerm": "12 months",
    }

    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": False}
    tracker.add_employee_to_tracker.return_value = {"success": True, "row_id": "10"}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    tracker.add_employee_to_tracker.assert_awaited_once()
    kwargs = tracker.add_employee_to_tracker.await_args.kwargs
    assert kwargs["staff_name"] == "Alice Example"
    assert kwargs["staff_email"] == "alice@example.com"
    assert kwargs["requested_start_date"] == "2026-04-01"
    assert kwargs["job_title"] == "Teacher"
    assert kwargs["work_location"] == "Bronx"
    assert kwargs["requesting_manager"] == "manager@example.com"
    assert kwargs["status_change"] == "New hire"
    assert kwargs["staff_phone"] == "555-0000"
    assert kwargs["education_level"] == "Bachelors"
    assert kwargs["supplements"] == "None"
    assert kwargs["license_number"] == "LIC-123"
    assert kwargs["uploaded_credentials"] == "Yes"
    assert kwargs["compensation"] == "65000"
    assert kwargs["employment_type"] == "Full-time"
    assert kwargs["contract_term"] == "12 months"


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_to_new_hire_executor_by_default() -> None:
    payload = {"staffEmail": "alice@example.com"}
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_onboarding_submission", new=AsyncMock()) as onboarding,
        patch("onboarding_agent.runtime.jobs._process_offboarding_submission", new=AsyncMock()) as offboarding,
        patch("onboarding_agent.runtime.jobs._process_temporary_submission", new=AsyncMock()) as temporary,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_awaited_once_with(payload)
    onboarding.assert_not_called()
    offboarding.assert_not_called()
    temporary.assert_not_called()


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_to_status_change_workflow() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Promotion",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_onboarding_submission", new=AsyncMock()) as onboarding,
        patch("onboarding_agent.runtime.jobs._process_offboarding_submission", new=AsyncMock()) as offboarding,
        patch("onboarding_agent.runtime.jobs._process_temporary_submission", new=AsyncMock()) as temporary,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    onboarding.assert_awaited_once_with(payload, "promotion")
    offboarding.assert_not_called()
    temporary.assert_not_called()


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_unknown_status_change_to_non_new_hire() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Future Workflow",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_onboarding_submission", new=AsyncMock()) as onboarding,
        patch("onboarding_agent.runtime.jobs._process_offboarding_submission", new=AsyncMock()) as offboarding,
        patch("onboarding_agent.runtime.jobs._process_temporary_submission", new=AsyncMock()) as temporary,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    onboarding.assert_awaited_once_with(payload, "other")
    offboarding.assert_not_called()
    temporary.assert_not_called()


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_offboarding_workflow_to_offboard_executor() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Transfer Out",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_onboarding_submission", new=AsyncMock()) as onboarding,
        patch("onboarding_agent.runtime.jobs._process_offboarding_submission", new=AsyncMock()) as offboarding,
        patch("onboarding_agent.runtime.jobs._process_temporary_submission", new=AsyncMock()) as temporary,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    onboarding.assert_not_called()
    temporary.assert_not_called()
    offboarding.assert_awaited_once_with(payload, "transfer_out")


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_temporary_workflow_to_temp_executor() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Leave Start",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_onboarding_submission", new=AsyncMock()) as onboarding,
        patch("onboarding_agent.runtime.jobs._process_offboarding_submission", new=AsyncMock()) as offboarding,
        patch("onboarding_agent.runtime.jobs._process_temporary_submission", new=AsyncMock()) as temporary,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    onboarding.assert_not_called()
    offboarding.assert_not_called()
    temporary.assert_awaited_once_with(payload, "leave_start")


@pytest.mark.asyncio
async def test_process_new_hire_job_requires_composite_identity_fields() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "statusChange": "Promotion",
        "jobTitle": "",
        "workLocation": "Bronx",
    }

    from onboarding_agent.runtime.jobs import process_new_hire_job

    with pytest.raises(ValueError, match="composite identity"):
        await process_new_hire_job(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_change", "expected_stages"),
    [
        (
            "Promotion",
            {
                "Background Submission",
                "Background Cleared",
                "Employee Complete ADP Profile",
                "Clear to Start",
                "Drug Screening",
            },
        ),
        (
            "Pay Increase",
            {
                "Added to Staff Roster",
                "Background Submission",
                "Background Cleared",
                "Employee Complete ADP Profile",
                "Clear to Start",
                "Drug Screening",
            },
        ),
        (
            "Transfer In",
            {
                "Background Submission",
                "Background Cleared",
                "Employee Complete ADP Profile",
            },
        ),
        (
            "Rehire",
            {
                "Employee Complete ADP Profile",
            },
        ),
    ],
)
async def test_non_new_hire_workflow_marks_excluded_stages_na(
    status_change: str,
    expected_stages: set[str],
) -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "statusChange": status_change,
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True}
    tracker.update_stage.return_value = {"success": True}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-1"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=AsyncMock(return_value={"success": True})),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    updated_stages = {call.args[1] for call in tracker.update_stage.await_args_list}
    assert updated_stages == expected_stages
    for call in tracker.update_stage.await_args_list:
        assert call.kwargs["value"] == "N/A"


@pytest.mark.asyncio
async def test_promotion_workflow_does_not_draft_welcome_email() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "statusChange": "Promotion",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True}
    tracker.update_stage.return_value = {"success": True}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-1"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}
    draft_email = AsyncMock(return_value={"success": True})
    save_card = AsyncMock()

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=draft_email),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=save_card),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    draft_email.assert_not_awaited()
    save_kwargs = save_card.await_args.kwargs
    assert save_kwargs["allow_email_action"] is False
    assert save_kwargs["allow_docusign_action"] is True
    assert save_kwargs["title"] == "Promotion Requested"


@pytest.mark.asyncio
async def test_rehire_workflow_drafts_welcome_email_and_keeps_docusign_action() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "statusChange": "Rehire",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True}
    tracker.update_stage.return_value = {"success": True}
    docusign = AsyncMock()
    docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-1"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}
    draft_email = AsyncMock(return_value={"success": True})
    save_card = AsyncMock()

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.draft_onboarding_email_for_employee", new=draft_email),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=save_card),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    draft_email.assert_awaited_once()
    save_kwargs = save_card.await_args.kwargs
    assert save_kwargs["allow_email_action"] is True
    assert save_kwargs["allow_docusign_action"] is True
    assert save_kwargs["title"] == "Rehire Requested"


@pytest.mark.asyncio
async def test_second_position_workflow_uses_action_card_instead_of_new_hire_card() -> None:
    payload = {
        "submissionId": "sub-789",
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "statusChange": "Second Position",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True}
    tracker.update_stage.return_value = {"success": True}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()) as save_new_hire,
        patch("onboarding_agent.runtime.jobs.save_separation_card", new=AsyncMock()) as save_workflow,
        patch("onboarding_agent.integrations.adaptive_cards.separation_card", return_value={"type": "AdaptiveCard"}) as build_action_card,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    save_new_hire.assert_not_awaited()
    build_action_card.assert_called_once()
    assert build_action_card.call_args.kwargs["submission_id"] == "sub-789"
    assert build_action_card.call_args.kwargs["action_name"] == "add_to_staff_roster"
    save_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_promotion_workflow_defers_docusign_draft_creation_until_card_action() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "staffName": "Alice Example",
        "jobTitle": "Teacher",
        "workLocation": "Bronx",
        "statusChange": "Promotion",
    }
    tracker = AsyncMock()
    tracker.find_employee_in_tracker.return_value = {"found": True}
    tracker.update_stage.return_value = {"success": True}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)
