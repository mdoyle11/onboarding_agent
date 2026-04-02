"""Tests for composite-keyed adaptive card state."""

from __future__ import annotations

import pytest

from onboarding_agent.integrations.card_state import (
    get_new_hire_card,
    mark_new_hire_action_complete,
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

        ambiguous = await get_new_hire_card("mdoyle@bridgeprepacademy.com")
        bronx = await get_new_hire_card("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher")
        queens = await get_new_hire_card("mdoyle@bridgeprepacademy.com", "Queens", "Teacher")

        assert ambiguous is None
        assert bronx is not None
        assert bronx["message_id"] == "msg-1"
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
            "mdoyle@bridgeprepacademy.com",
            "send_docusign",
            "Queens",
            "Teacher",
        )

        bronx = await get_new_hire_card("mdoyle@bridgeprepacademy.com", "Bronx", "Teacher")
        queens = await get_new_hire_card("mdoyle@bridgeprepacademy.com", "Queens", "Teacher")

        assert result is not None
        assert bronx is not None
        assert bronx["docusign_sent"] is False
        assert queens is not None
        assert queens["docusign_sent"] is True
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
