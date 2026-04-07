"""Tests for composite-keyed adaptive card state."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.domain.identity import EmployeeIdentity
from onboarding_agent.integrations.adaptive_cards import new_hire_card
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    get_new_hire_card,
    mark_new_hire_action_complete,
    refresh_docusign_status_card,
    refresh_new_hire_card,
    save_docusign_status_card,
    save_new_hire_card,
)
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import TTL_SECONDS_FIELD, FileStateStore


@pytest.mark.asyncio
async def test_new_hire_card_state_is_composite_keyed(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Bronx",
            job_title="Teacher",
            channel_id="channel-1",
            message_id="msg-1",
            submission_id="sub-1",
            employee_name="Matthew Doyle",
            title="New Hire Requested",
        )
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Queens",
            job_title="Teacher",
            channel_id="channel-1",
            message_id="msg-2",
            employee_name="Matthew Doyle",
            title="Pay Increase Requested",
        )

        ambiguous = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com"))
        bronx = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher"))
        queens = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Queens", "Teacher"))

        assert ambiguous is None
        assert bronx is not None
        assert bronx["message_id"] == "msg-1"
        assert bronx["submission_id"] == "sub-1"
        assert queens is not None
        assert queens["message_id"] == "msg-2"
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_mark_new_hire_action_complete_only_updates_matching_composite_card(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Bronx",
            job_title="Teacher",
            channel_id="channel-1",
            message_id="msg-1",
            employee_name="Matthew Doyle",
            title="New Hire Requested",
        )
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Queens",
            job_title="Teacher",
            channel_id="channel-1",
            message_id="msg-2",
            employee_name="Matthew Doyle",
            title="Pay Increase Requested",
        )

        result = await mark_new_hire_action_complete(
            EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Queens", "Teacher"),
            "create_docusign_draft",
        )

        bronx = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher"))
        queens = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Queens", "Teacher"))

        assert result is not None
        assert bronx is not None
        assert bronx["docusign_draft_created"] is False
        assert queens is not None
        assert queens["docusign_draft_created"] is True
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_get_new_hire_card_does_not_fallback_when_submission_id_does_not_match(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            channel_id="channel-1",
            message_id="msg-1",
            submission_id="sub-1",
            employee_name="Matthew Doyle",
            title="New Hire Requested",
        )
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Orange",
            job_title="Teacher",
            status_change="Pay Increase",
            channel_id="channel-1",
            message_id="msg-2",
            submission_id="sub-2",
            employee_name="Matthew Doyle",
            title="Pay Increase Requested",
        )

        result = await get_new_hire_card(
            EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"),
            submission_id="sub-2",
        )

        assert result is not None
        assert result["message_id"] == "msg-2"

        missing = await get_new_hire_card(
            EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"),
            submission_id="sub-missing",
        )

        assert missing is None
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_get_docusign_card_does_not_fallback_when_submission_id_does_not_match(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_docusign_status_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            employee_name="Matthew Doyle",
            channel_id="channel-1",
            message_id="doc-msg-1",
            envelope_id="env-1",
            status="created",
            summary="Draft 1",
            submission_id="sub-1",
            work_location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
        )
        await save_docusign_status_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            employee_name="Matthew Doyle",
            channel_id="channel-1",
            message_id="doc-msg-2",
            envelope_id="env-2",
            status="created",
            summary="Draft 2",
            submission_id="sub-2",
            work_location="Orange",
            job_title="Teacher",
            status_change="Pay Increase",
        )

        result = await get_docusign_status_card(
            EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"),
            submission_id="sub-2",
        )

        assert result is not None
        assert result["message_id"] == "doc-msg-2"

        missing = await get_docusign_status_card(
            EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"),
            submission_id="sub-missing",
        )

        assert missing is None
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_new_hire_card_state_ttl_metadata_is_not_persisted_in_payload(tmp_path) -> None:
    previous_store = store_mod.store
    store = FileStateStore(str(tmp_path))
    store_mod.store = store
    try:
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            channel_id="channel-1",
            message_id="msg-1",
            employee_name="Matthew Doyle",
            title="New Hire Requested",
        )

        stored = await store.get("new_hire_card", "mdoyle@bridgeprepacademy.com|bronx|teacher|new hire")

        assert stored is not None
        assert TTL_SECONDS_FIELD not in stored
    finally:
        store_mod.store = previous_store


@pytest.mark.asyncio
async def test_refresh_new_hire_card_rehydrates_from_tracker_and_migrates_key(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_new_hire_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            work_location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            channel_id="channel-1",
            message_id="msg-1",
            submission_id="sub-1",
            employee_name="Matt",
            title="New Hire Requested",
            requested_start_date="2026-04-01",
        )

        tracker = AsyncMock()
        tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "name": "Matthew Doyle",
            "email": "mdoyle@bridgeprepacademy.com",
            "submission_id": "sub-1",
            "location": "Collier",
            "job_title": "Instructional Coach",
            "status_change": "Transfer In",
            "start_date": "2026-05-01",
        }

        with (
            patch(
                "onboarding_agent.integrations.workbook.tracker_client.TrackerClient",
                return_value=tracker,
            ),
            patch(
                "onboarding_agent.integrations.teams.proactive.update_proactive_card",
                new=AsyncMock(return_value={"success": True}),
            ) as update_card,
        ):
            result = await refresh_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"))

        assert result["success"] is True
        updated = await get_new_hire_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Collier", "Instructional Coach", "Transfer In"))
        assert updated is not None
        assert updated["employee_name"] == "Matthew Doyle"
        assert updated["requested_start_date"] == "2026-05-01"
        card = update_card.await_args.kwargs["card"]
        facts = card["body"][2]["facts"]
        assert {"title": "Job Title", "value": "Instructional Coach"} in facts
        assert {"title": "Work Location", "value": "Collier"} in facts
    finally:
        store_mod.store = previous_store


def test_new_hire_card_formats_requested_start_date_for_display() -> None:
    card = new_hire_card(
        employee_name="Matthew Doyle",
        employee_email="mdoyle@bridgeprepacademy.com",
        summary="Summary",
        requested_start_date="2026-04-16",
    )

    facts = card["body"][2]["facts"]
    requested_start_date_fact = next(fact for fact in facts if fact["title"] == "Requested Start Date")
    assert requested_start_date_fact["value"] == "04/16/2026"


@pytest.mark.asyncio
async def test_refresh_docusign_status_card_rehydrates_from_tracker_and_migrates_key(tmp_path) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))
    try:
        await save_docusign_status_card(
            employee_email="mdoyle@bridgeprepacademy.com",
            channel_id="channel-1",
            message_id="msg-2",
            envelope_id="env-1",
            status="created",
            summary="Draft ready.",
            submission_id="sub-1",
            work_location="Bronx",
            job_title="Teacher",
            status_change="New Hire",
            review_url="https://review.example.com/env-1",
            allow_send_action=True,
        )

        tracker = AsyncMock()
        tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "email": "mdoyle@bridgeprepacademy.com",
            "submission_id": "sub-1",
            "location": "Collier",
            "job_title": "Instructional Coach",
            "status_change": "Transfer In",
        }

        with (
            patch(
                "onboarding_agent.integrations.workbook.tracker_client.TrackerClient",
                return_value=tracker,
            ),
            patch(
                "onboarding_agent.integrations.teams.proactive.update_proactive_card",
                new=AsyncMock(return_value={"success": True}),
            ) as update_card,
        ):
            result = await refresh_docusign_status_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher", "New Hire"))

        assert result["success"] is True
        updated = await get_docusign_status_card(EmployeeIdentity("mdoyle@bridgeprepacademy.com", "Collier", "Instructional Coach", "Transfer In"))
        assert updated is not None
        assert updated["submission_id"] == "sub-1"
        card = update_card.await_args.kwargs["card"]
        facts = card["body"][2]["facts"]
        assert {"title": "Employee", "value": "mdoyle@bridgeprepacademy.com"} in facts
        assert {"title": "Location", "value": "Collier"} in facts
        assert {"title": "Job Title", "value": "Instructional Coach"} in facts
        send_action = next(action for action in card["actions"] if action.get("title") == "Send Offer Letter")
        assert send_action["data"]["job_title"] == "Instructional Coach"
        assert send_action["data"]["work_location"] == "Collier"
    finally:
        store_mod.store = previous_store
