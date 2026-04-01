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
    )


@pytest.mark.asyncio
async def test_process_background_clearance_job_uses_composite_identity_for_stage_updates() -> None:
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
        "workLocation": "Bronx",
        "jobTitle": "Teacher",
    }
    tracker = AsyncMock()
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
        patch("onboarding_agent.runtime.jobs._process_non_new_hire_submission", new=AsyncMock()) as non_new_hire,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_awaited_once_with(payload)
    non_new_hire.assert_not_called()


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_to_status_change_workflow() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Promotion",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_non_new_hire_submission", new=AsyncMock()) as non_new_hire,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    non_new_hire.assert_awaited_once_with(payload, "promotion")


@pytest.mark.asyncio
async def test_process_new_hire_job_routes_unknown_status_change_to_non_new_hire() -> None:
    payload = {
        "staffEmail": "alice@example.com",
        "statusChange": "Future Workflow",
    }
    with (
        patch("onboarding_agent.runtime.jobs._process_new_hire_submission", new=AsyncMock()) as new_hire,
        patch("onboarding_agent.runtime.jobs._process_non_new_hire_submission", new=AsyncMock()) as non_new_hire,
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    new_hire.assert_not_called()
    non_new_hire.assert_awaited_once_with(payload, "other")


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
async def test_promotion_workflow_creates_docusign_draft_when_missing() -> None:
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
    docusign.check_draft_exists.return_value = {"exists": False}
    docusign.create_envelope_draft.return_value = {"success": True, "envelope_id": "env-2"}
    teams = AsyncMock()
    teams.send_channel_notification.return_value = {"success": True, "message_id": "msg-1"}

    with (
        patch("onboarding_agent.runtime.jobs.TrackerClient", return_value=tracker),
        patch("onboarding_agent.runtime.jobs.DocuSignClient", return_value=docusign),
        patch("onboarding_agent.runtime.jobs.TeamsMessenger", return_value=teams),
        patch("onboarding_agent.runtime.jobs.reset_new_hire_card_actions", new=AsyncMock()),
        patch("onboarding_agent.runtime.jobs.save_new_hire_card", new=AsyncMock()),
    ):
        from onboarding_agent.runtime.jobs import process_new_hire_job

        await process_new_hire_job(payload)

    docusign.check_draft_exists.assert_awaited_once_with(
        "alice@example.com",
        "Bronx",
        "Teacher",
        "Promotion",
    )
    docusign.create_envelope_draft.assert_awaited_once()
