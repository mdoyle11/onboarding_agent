"""Tests for chat history serialization and persistence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from onboarding_agent.integrations.teams.memory import (
    deserialize_messages,
    get_or_create_session_key,
    load_chat_history,
    save_chat_history,
    serialize_messages,
)


def test_serialize_deserialize_round_trip():
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there!"),
    ]
    serialized = serialize_messages(messages)
    deserialized = deserialize_messages(serialized)

    assert len(deserialized) == 3
    assert isinstance(deserialized[0], SystemMessage)
    assert isinstance(deserialized[1], HumanMessage)
    assert isinstance(deserialized[2], AIMessage)
    assert deserialized[0].content == "You are a helpful assistant."
    assert deserialized[1].content == "Hello"
    assert deserialized[2].content == "Hi there!"


def test_serialize_ai_message_with_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "find_employee", "args": {"email": "a@b.com"}, "id": "tc1"}],
    )
    serialized = serialize_messages([msg])
    assert serialized[0]["tool_calls"] == msg.tool_calls

    deserialized = deserialize_messages(serialized)
    assert isinstance(deserialized[0], AIMessage)
    assert deserialized[0].tool_calls == msg.tool_calls


def test_serialize_tool_message():
    msg = ToolMessage(content='{"success": true}', tool_call_id="tc1", name="find_employee")
    serialized = serialize_messages([msg])
    assert serialized[0]["type"] == "tool"
    assert serialized[0]["tool_call_id"] == "tc1"
    assert serialized[0]["name"] == "find_employee"

    deserialized = deserialize_messages(serialized)
    assert isinstance(deserialized[0], ToolMessage)
    assert deserialized[0].tool_call_id == "tc1"
    assert deserialized[0].name == "find_employee"


def test_deserialize_empty_list():
    assert deserialize_messages([]) == []


@pytest.mark.asyncio
async def test_load_chat_history_returns_empty_for_missing_key():
    mock_store = AsyncMock()
    mock_store.get = AsyncMock(return_value=None)

    with patch("onboarding_agent.integrations.teams.memory.store_mod") as mock_mod:
        mock_mod.session_store = mock_store
        result = await load_chat_history("session-123")

    assert result == []


@pytest.mark.asyncio
async def test_save_and_load_round_trip():
    storage: dict[str, dict] = {}

    async def mock_put(ns: str, key: str, value: dict) -> None:
        storage[f"{ns}:{key}"] = value

    async def mock_get(ns: str, key: str) -> dict | None:
        return storage.get(f"{ns}:{key}")

    mock_store = AsyncMock()
    mock_store.put = mock_put
    mock_store.get = mock_get

    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hello"),
        AIMessage(content="hi"),
    ]

    with patch("onboarding_agent.integrations.teams.memory.store_mod") as mock_mod:
        mock_mod.session_store = mock_store
        await save_chat_history("session-1", messages)
        loaded = await load_chat_history("session-1")

    # System messages are stripped before saving
    assert len(loaded) == 2
    assert isinstance(loaded[0], HumanMessage)
    assert isinstance(loaded[1], AIMessage)


@pytest.mark.asyncio
async def test_get_or_create_session_key_reuses_existing_session():
    activity = SimpleNamespace(
        conversation=SimpleNamespace(id="conv-1", conversation_type="personal"),
        from_property=SimpleNamespace(aad_object_id="user-1"),
    )
    existing_session = {
        "session_id": "20260330T120000Z-abcd",
        "turn_count": 2,
        "last_activity_at": "2026-03-30T12:05:00Z",
    }

    mock_store = AsyncMock()
    mock_store.get = AsyncMock(return_value=existing_session)
    mock_store.put = AsyncMock()

    with (
        patch("onboarding_agent.integrations.teams.memory.store_mod") as mock_mod,
        patch("onboarding_agent.integrations.teams.memory._now_utc") as mock_now,
    ):
        mock_mod.session_store = mock_store
        mock_now.return_value = SimpleNamespace(
            isoformat=lambda: "2026-03-30T12:10:00+00:00",
            strftime=lambda _fmt: "20260330T121000Z",
            __sub__=lambda self, other: None,
        )
        # Use a real datetime to preserve timedelta comparison behavior.
        from datetime import UTC, datetime
        mock_now.return_value = datetime(2026, 3, 30, 12, 10, tzinfo=UTC)
        result = await get_or_create_session_key(activity)

    assert result == "teams:dm:conv-1:20260330T120000Z-abcd"
    mock_store.put.assert_awaited_once()
