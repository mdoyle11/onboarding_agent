"""Tests for queued job handling."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from onboarding_agent.runtime.job_queue import QueueJob
from onboarding_agent.runtime.jobs import (
    JOB_DOCUSIGN,
    JOB_NEW_HIRE,
    build_background_clearance_messages,
    build_docusign_messages,
    build_new_hire_messages,
    process_job,
)


def test_build_new_hire_messages_returns_human_message() -> None:
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
        "startDate": "2026-04-01",
        "department": "HR",
        "location": "NYC",
        "managerEmail": "manager@example.com",
        "submissionId": "sub-123",
    }

    messages = build_new_hire_messages(payload)

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert "alice@example.com" in messages[0].content
    assert "Alice Example" in messages[0].content


def test_build_docusign_messages_returns_human_message() -> None:
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }

    messages = build_docusign_messages(payload)

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert "env-123" in messages[0].content
    assert "completed" in messages[0].content


def test_build_background_clearance_messages_returns_human_message() -> None:
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
    }

    messages = build_background_clearance_messages(payload)

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert "alice@example.com" in messages[0].content


@pytest.mark.asyncio
async def test_process_job_invokes_agent_for_new_hire() -> None:
    mock_run = AsyncMock(return_value=[])
    payload = {"employeeEmail": "alice@example.com"}

    with patch("onboarding_agent.runtime.jobs.run_agent", mock_run):
        await process_job(QueueJob(job_type=JOB_NEW_HIRE, payload=payload))

    mock_run.assert_awaited_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs["trigger_source"] == "pa_webhook"


@pytest.mark.asyncio
async def test_process_job_invokes_agent_for_docusign() -> None:
    mock_run = AsyncMock(return_value=[])
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }

    with patch("onboarding_agent.runtime.jobs.run_agent", mock_run):
        await process_job(QueueJob(job_type=JOB_DOCUSIGN, payload=payload))

    mock_run.assert_awaited_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs["trigger_source"] == "pa_webhook"
