"""Tests for queued new-hire job handling."""

from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.runtime.job_queue import QueueJob
from onboarding_agent.runtime.jobs import (
    JOB_BACKGROUND_CLEARANCE,
    JOB_DOCUSIGN,
    JOB_NEW_HIRE,
    build_background_clearance_state,
    build_docusign_state,
    build_new_hire_state,
    process_job,
)


def test_build_new_hire_state_populates_expected_fields() -> None:
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
        "startDate": "2026-04-01",
        "department": "HR",
        "location": "NYC",
        "managerEmail": "manager@example.com",
        "submissionId": "sub-123",
    }

    state = build_new_hire_state(payload)

    assert state["employee_email"] == "alice@example.com"
    assert state["employee_name"] == "Alice Example"
    assert state["forms_submission_id"] == "sub-123"
    assert state["forms_data_raw"] == payload


def test_build_docusign_state_populates_expected_fields() -> None:
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }

    state = build_docusign_state(payload)

    assert state["employee_email"] == "alice@example.com"
    assert state["docusign_envelope_id"] == "env-123"
    assert state["docusign_envelope_status"] == "completed"


def test_build_background_clearance_state_populates_expected_fields() -> None:
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
    }

    state = build_background_clearance_state(payload)

    assert state["employee_email"] == "alice@example.com"
    assert state["employee_name"] == "Alice Example"


@pytest.mark.asyncio
async def test_process_job_invokes_graph_for_new_hire() -> None:
    compiled = AsyncMock()
    payload = {"employeeEmail": "alice@example.com"}

    with patch("onboarding_agent.runtime.jobs.graph_module.compiled_graph", compiled):
        await process_job(QueueJob(job_type=JOB_NEW_HIRE, payload=payload))

    compiled.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_job_invokes_graph_for_docusign() -> None:
    compiled = AsyncMock()
    payload = {
        "envelope_id": "env-123",
        "status": "completed",
        "employee_email": "alice@example.com",
    }

    with patch("onboarding_agent.runtime.jobs.graph_module.compiled_graph", compiled):
        await process_job(QueueJob(job_type=JOB_DOCUSIGN, payload=payload))

    compiled.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_job_invokes_graph_for_background_clearance() -> None:
    compiled = AsyncMock()
    payload = {
        "employeeEmail": "alice@example.com",
        "employeeName": "Alice Example",
    }

    with patch("onboarding_agent.runtime.jobs.graph_module.compiled_graph", compiled):
        await process_job(QueueJob(job_type=JOB_BACKGROUND_CLEARANCE, payload=payload))

    compiled.ainvoke.assert_awaited_once()
