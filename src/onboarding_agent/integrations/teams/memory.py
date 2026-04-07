"""Ephemeral Teams session tracking and chat history persistence."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from onboarding_agent.agent.session_context import SESSION_CONTEXT_FIELDS
from onboarding_agent.integrations.teams.runtime import normalize_channel_conversation_id
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import TTL_SECONDS_FIELD

logger = logging.getLogger(__name__)

NS_CHAT_HISTORY = "chat_history"
NS_CONVERSATION_SESSION = "conversation_session"
NS_SESSION_CONTEXT = "session_context"
NS_THREAD_SEED_CONTEXT = "thread_seed_context"
_SESSION_INACTIVITY_LIMIT = timedelta(minutes=30)
_SESSION_MAX_TURNS = 10
_CHANNEL_THREAD_TTL = timedelta(days=7)
_THREAD_SEED_CONTEXT_TTL_SECONDS = 30 * 24 * 60 * 60
_CHAT_HISTORY_LIMIT = 4
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SessionContext = dict[str, Any]


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


def _normalize_stored_channel_id(value: str) -> str:
    return normalize_channel_conversation_id(unquote(str(value or "").strip()))


def _channel_thread_root_id(activity: Any) -> str:
    reply_to_id = str(getattr(activity, "reply_to_id", "") or "").strip()
    if reply_to_id:
        return reply_to_id

    conversation_id = str(getattr(getattr(activity, "conversation", None), "id", "") or "").strip()
    if ";messageid=" in conversation_id:
        return conversation_id.split(";messageid=", 1)[1]

    activity_id = str(getattr(activity, "id", "") or "").strip()
    if activity_id:
        return activity_id
    return ""


def _is_channel_thread_activity(activity: Any) -> bool:
    conversation_type = getattr(getattr(activity, "conversation", None), "conversation_type", "") or ""
    return conversation_type == "channel"


def _conversation_key(activity: Any) -> str:
    conversation_id = getattr(getattr(activity, "conversation", None), "id", "") or ""
    if conversation_id:
        category = _conversation_category(activity)
        if _is_channel_thread_activity(activity):
            conversation_id = normalize_channel_conversation_id(conversation_id)
            thread_root_id = _channel_thread_root_id(activity)
            if thread_root_id:
                return f"{category}:{conversation_id}:thread:{thread_root_id}"
        return f"{category}:{conversation_id}"

    from_property = getattr(activity, "from_property", None)
    user_id = getattr(from_property, "aad_object_id", "") or getattr(from_property, "id", "") or "anon"
    return f"{_conversation_category(activity)}:user:{user_id}"


def _should_rotate(session: dict[str, Any], now: datetime) -> bool:
    if str(session.get("category", "")).strip() == "channel":
        expires_at = _parse_timestamp(str(session.get("expires_at", "")))
        return expires_at is None or now >= expires_at

    turn_count = int(session.get("turn_count", 0) or 0)
    if turn_count >= _SESSION_MAX_TURNS:
        return True

    last_activity_at = _parse_timestamp(str(session.get("last_activity_at", "")))
    if last_activity_at is None:
        return True

    return now - last_activity_at > _SESSION_INACTIVITY_LIMIT


async def _delete_session_artifacts(key: str, session_id: str) -> None:
    session_key = f"teams:{key}:{session_id}"
    await _store().delete(NS_CHAT_HISTORY, session_key)
    await _store().delete(NS_SESSION_CONTEXT, session_key)


def _channel_thread_store_key(channel_id: str, message_id: str) -> str:
    conversation_id = _normalize_stored_channel_id(channel_id)
    root_message_id = str(message_id or "").strip()
    if not conversation_id or not root_message_id:
        return ""
    return f"channel:{conversation_id}:thread:{root_message_id}"


async def _ensure_session(
    key: str,
    *,
    category: str,
    is_channel_thread: bool,
    increment_turns: bool = False,
) -> tuple[str, str]:
    """Resolve or rotate a session for *key*. Returns ``(session_id, session_key)``."""
    now = _now_utc()
    session = await _store().get(NS_CONVERSATION_SESSION, key)

    if session is None or _should_rotate(session, now):
        if session is not None:
            previous_session_id = str(session.get("session_id", "")).strip()
            if previous_session_id:
                await _delete_session_artifacts(key, previous_session_id)
        session_id = _session_id()
        turn_count = 1
    else:
        session_id = str(session.get("session_id", "")).strip() or _session_id()
        turn_count = int(session.get("turn_count", 0) or 0) + (1 if increment_turns else 0)

    payload: dict[str, Any] = {
        "session_id": session_id,
        "last_activity_at": now.isoformat().replace("+00:00", "Z"),
        "category": category,
    }
    if is_channel_thread:
        payload["expires_at"] = (now + _CHANNEL_THREAD_TTL).isoformat().replace("+00:00", "Z")
    else:
        payload["turn_count"] = turn_count

    await _store().put(NS_CONVERSATION_SESSION, key, payload)
    return session_id, f"teams:{key}:{session_id}"


async def get_or_create_session_key(activity: Any) -> str:
    """Return the current Teams session key, rotating when needed."""
    key = _conversation_key(activity)
    is_channel_thread = _is_channel_thread_activity(activity)

    _sid, session_key = await _ensure_session(
        key,
        category=_conversation_category(activity),
        is_channel_thread=is_channel_thread,
        increment_turns=True,
    )
    if is_channel_thread:
        seeded_context = await _load_thread_seed_context(key)
        if seeded_context:
            await merge_session_context(session_key, seeded_context)
    return session_key


async def seed_channel_thread_context(
    channel_id: str,
    message_id: str,
    context: SessionContext,
) -> str:
    """Seed session context for a proactive channel thread rooted at *message_id*."""
    key = _channel_thread_store_key(channel_id, message_id)
    if not key:
        return ""

    _sid, session_key = await _ensure_session(
        key,
        category="channel",
        is_channel_thread=True,
    )
    if context:
        await _store().put(NS_THREAD_SEED_CONTEXT, key, {
            **_sanitize_session_context(context),
            TTL_SECONDS_FIELD: _THREAD_SEED_CONTEXT_TTL_SECONDS,
        })
        await merge_session_context(session_key, context)
    return session_key


async def _load_thread_seed_context(key: str) -> SessionContext:
    record = await _store().get(NS_THREAD_SEED_CONTEXT, key)
    if record is None or not isinstance(record, dict):
        return {}
    return _sanitize_session_context(record)


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


def _persistable_chat_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Keep only conversational messages that are useful across turns."""
    persisted: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            persisted.append(msg)
        elif isinstance(msg, AIMessage) and msg.content:
            persisted.append(AIMessage(content=msg.content))
    return persisted


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
    bounded = _persistable_chat_messages(non_system)[-_CHAT_HISTORY_LIMIT:]
    await _store().put(
        NS_CHAT_HISTORY,
        session_key,
        {"messages": serialize_messages(bounded)},
    )


async def load_session_context(session_key: str) -> SessionContext:
    """Load compact structured session context for a Teams conversation."""
    record = await _store().get(NS_SESSION_CONTEXT, session_key)
    if record is None or not isinstance(record, dict):
        return {}

    return _sanitize_session_context(record)


async def save_session_context(session_key: str, context: SessionContext) -> None:
    """Persist compact structured session context for a Teams conversation."""
    payload = _sanitize_session_context(context)
    if payload:
        payload["last_updated_at"] = _now_utc().isoformat().replace("+00:00", "Z")
    await _store().put(NS_SESSION_CONTEXT, session_key, payload)


async def merge_session_context(session_key: str, patch: SessionContext) -> SessionContext:
    """Merge a partial context update into the stored session context."""
    current = await load_session_context(session_key)
    merged: SessionContext = dict(current)
    for key, value in patch.items():
        if value in (None, ""):
            continue
        merged[key] = value
    await save_session_context(session_key, merged)
    return merged


def extract_context_patch_from_text(text: str) -> SessionContext:
    """Infer a small context patch from a user message."""
    lowered = text.strip().lower()
    patch: SessionContext = {}

    email_match = _EMAIL_PATTERN.search(text)
    if email_match:
        patch["employee_email"] = email_match.group(0)

    if "status" in lowered or "where is" in lowered or "signed" in lowered:
        patch["intent"] = "check_onboarding_status"
    elif "offer letter" in lowered or "docusign" in lowered:
        patch["intent"] = "send_docusign_envelope"
    elif "onboarding email" in lowered or "welcome email" in lowered:
        patch["intent"] = "send_onboarding_email"
    elif "staff roster" in lowered:
        patch["intent"] = "staff_roster"
    elif "background" in lowered:
        patch["intent"] = "background_clearance"

    return patch


def _sanitize_session_context(context: SessionContext) -> SessionContext:
    return {
        key: value for key, value in context.items()
        if key in SESSION_CONTEXT_FIELDS and value not in (None, "")
    }
