"""Ephemeral Teams session tracking and chat history persistence."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from onboarding_agent.runtime import state_store as store_mod

logger = logging.getLogger(__name__)

NS_CHAT_HISTORY = "chat_history"
NS_CONVERSATION_SESSION = "conversation_session"
_SESSION_INACTIVITY_LIMIT = timedelta(minutes=30)
_SESSION_MAX_TURNS = 10


def _store() -> store_mod.StateStore:
    assert store_mod.session_store is not None, "Session store not initialized"
    return store_mod.session_store


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _session_id() -> str:
    return f"{_now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:4]}"


def _conversation_category(activity: Any) -> str:
    conversation_type = getattr(getattr(activity, "conversation", None), "conversation_type", "") or ""
    if conversation_type in ("channel", "groupChat"):
        return "channel"
    return "dm"


def _conversation_key(activity: Any) -> str:
    conversation_id = getattr(getattr(activity, "conversation", None), "id", "") or ""
    if conversation_id:
        return f"{_conversation_category(activity)}:{conversation_id}"

    from_property = getattr(activity, "from_property", None)
    user_id = getattr(from_property, "aad_object_id", "") or getattr(from_property, "id", "") or "anon"
    return f"{_conversation_category(activity)}:user:{user_id}"


def _should_rotate(session: dict[str, Any], now: datetime) -> bool:
    turn_count = int(session.get("turn_count", 0) or 0)
    if turn_count >= _SESSION_MAX_TURNS:
        return True

    last_activity_at = _parse_timestamp(str(session.get("last_activity_at", "")))
    if last_activity_at is None:
        return True

    return now - last_activity_at > _SESSION_INACTIVITY_LIMIT


async def get_or_create_session_key(activity: Any) -> str:
    """Return the current Teams session key, rotating when needed."""
    now = _now_utc()
    key = _conversation_key(activity)
    session = await _store().get(NS_CONVERSATION_SESSION, key)

    if session is None or _should_rotate(session, now):
        session_id = _session_id()
        turn_count = 1
    else:
        session_id = str(session.get("session_id", "")).strip() or _session_id()
        turn_count = int(session.get("turn_count", 0) or 0) + 1

    await _store().put(
        NS_CONVERSATION_SESSION,
        key,
        {
            "session_id": session_id,
            "turn_count": turn_count,
            "last_activity_at": now.isoformat().replace("+00:00", "Z"),
            "category": _conversation_category(activity),
        },
    )
    return f"teams:{key}:{session_id}"


def serialize_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Convert a list of BaseMessage objects to JSON-serializable dicts."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"type": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            result.append({"type": "human", "content": msg.content})
        elif isinstance(msg, AIMessage):
            entry: dict[str, Any] = {"type": "ai", "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            result.append(entry)
        elif isinstance(msg, ToolMessage):
            result.append({
                "type": "tool",
                "content": msg.content,
                "tool_call_id": msg.tool_call_id,
                "name": msg.name or "",
            })
    return result


def deserialize_messages(data: list[dict[str, Any]]) -> list[BaseMessage]:
    """Reconstruct BaseMessage objects from serialized dicts."""
    messages: list[BaseMessage] = []
    for entry in data:
        msg_type = entry.get("type", "")
        content = entry.get("content", "")
        if msg_type == "system":
            messages.append(SystemMessage(content=content))
        elif msg_type == "human":
            messages.append(HumanMessage(content=content))
        elif msg_type == "ai":
            messages.append(AIMessage(content=content, tool_calls=entry.get("tool_calls", [])))
        elif msg_type == "tool":
            messages.append(ToolMessage(
                content=content,
                tool_call_id=entry.get("tool_call_id", ""),
                name=entry.get("name", ""),
            ))
    return messages


async def load_chat_history(session_key: str) -> list[BaseMessage]:
    """Load chat history for a session from the state store."""
    record = await _store().get(NS_CHAT_HISTORY, session_key)
    if record is None:
        return []
    raw_messages = record.get("messages", [])
    if not isinstance(raw_messages, list):
        return []
    return deserialize_messages(raw_messages)


async def save_chat_history(session_key: str, messages: list[BaseMessage]) -> None:
    """Save chat history for a session to the state store."""
    non_system = [msg for msg in messages if not isinstance(msg, SystemMessage)]
    await _store().put(
        NS_CHAT_HISTORY,
        session_key,
        {"messages": serialize_messages(non_system)},
    )
