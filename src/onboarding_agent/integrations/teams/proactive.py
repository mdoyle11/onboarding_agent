"""Conversation reference store and proactive messaging for the Agents SDK."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, cast

from microsoft_agents.activity import (
    Activity,
    Attachment,
    ConversationReference,
)
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import TurnContext

from onboarding_agent.integrations.teams.runtime import (
    load_agents_sdk_config,
    normalize_channel_conversation_id,
)
from onboarding_agent.runtime import state_store as store_mod

logger = logging.getLogger(__name__)

adapter: CloudAdapter | None = None
bot_app_id: str = ""

NS_CONVERSATION_REF = "conversation_ref"


def _store() -> store_mod.StateStore:
    assert store_mod.store is not None, "State store not initialized"
    return store_mod.store


def _serialize_ref(ref: ConversationReference) -> dict[str, Any]:
    return cast(dict[str, Any], ref.model_dump(mode="json", by_alias=True, exclude_none=True))


def _deserialize_ref(data: dict[str, Any]) -> ConversationReference:
    return ConversationReference.model_validate(data)


async def save_conversation_reference(activity: Activity) -> None:
    """Extract and store the conversation reference from an incoming activity."""
    ref = activity.get_conversation_reference()
    if ref.conversation and ref.conversation.id:
        ref.conversation.id = normalize_channel_conversation_id(ref.conversation.id)
    channel_key = ref.conversation.id if ref.conversation else ""
    if not channel_key:
        return

    await _store().put(NS_CONVERSATION_REF, channel_key, _serialize_ref(ref))
    logger.debug("Stored conversation reference for %s", channel_key)


async def get_conversation_reference(channel_id: str) -> ConversationReference | None:
    """Look up a stored conversation reference by channel ID."""
    refs = await _store().get_all(NS_CONVERSATION_REF)

    if channel_id in refs:
        return _deserialize_ref(refs[channel_id])
    for key, data in refs.items():
        if channel_id in key or key in channel_id:
            return _deserialize_ref(data)
        conversation = data.get("conversation", {})
        if channel_id and conversation.get("name") == channel_id:
            return _deserialize_ref(data)

    for data in refs.values():
        conversation = data.get("conversation", {})
        if conversation.get("conversationType") == "channel":
            logger.info(
                "Falling back to stored channel conversation ref for requested channel %s",
                channel_id,
            )
            return _deserialize_ref(data)

    if refs:
        last_key = next(reversed(refs))
        logger.info(
            "Falling back to last stored conversation ref %s for requested channel %s",
            last_key,
            channel_id,
        )
        return _deserialize_ref(refs[last_key])
    return None


def _ensure_adapter() -> CloudAdapter | None:
    global adapter
    if adapter is not None:
        return adapter

    try:
        config = load_agents_sdk_config()
        connection_manager = MsalConnectionManager(**config)
        adapter = CloudAdapter(connection_manager=connection_manager)
        logger.info("Initialised CloudAdapter for proactive Teams messaging")
        return adapter
    except Exception:
        logger.exception("Failed to initialise CloudAdapter for proactive Teams messaging")
        return None


async def send_proactive_message(
    channel_id: str,
    message: str,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a proactive message to a Teams channel with an optional Adaptive Card."""
    started = perf_counter()
    current_adapter = _ensure_adapter()
    if current_adapter is None:
        return {"success": False, "error": "Cloud adapter not initialized"}

    ref = await get_conversation_reference(channel_id)
    if ref is None:
        return {
            "success": False,
            "error": (
                f"No conversation reference for channel {channel_id}. "
                "The agent must first receive an install event or message from that channel."
            ),
        }

    result: dict[str, Any] = {"success": False}
    continuation_activity = ref.get_continuation_activity()
    # Force a fresh channel post rather than replying in an existing thread/message.
    if hasattr(continuation_activity, "id"):
        continuation_activity.id = None
    if hasattr(continuation_activity, "reply_to_id"):
        continuation_activity.reply_to_id = None

    async def _callback(turn_context: TurnContext) -> None:
        outgoing = Activity(type="message", text=message)
        if card is not None:
            outgoing.text = ""
            outgoing.attachments = [
                Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=card,
                )
            ]

        response = await turn_context.send_activity(outgoing)
        result["success"] = True
        result["message_id"] = getattr(response, "id", "") or ""

    try:
        await current_adapter.continue_conversation(bot_app_id, continuation_activity, _callback)
    except Exception as exc:
        logger.exception("Proactive message failed for channel %s", channel_id)
        result["error"] = str(exc)
    finally:
        logger.info(
            "Proactive Teams send completed for %s in %.3fs success=%s",
            channel_id,
            perf_counter() - started,
            result.get("success", False),
        )

    return result


async def update_proactive_card(
    channel_id: str,
    message_id: str,
    card: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing proactive Teams card message."""
    started = perf_counter()
    current_adapter = _ensure_adapter()
    if current_adapter is None:
        return {"success": False, "error": "Cloud adapter not initialized"}

    ref = await get_conversation_reference(channel_id)
    if ref is None:
        return {
            "success": False,
            "error": (
                f"No conversation reference for channel {channel_id}. "
                "The agent must first receive an install event or message from that channel."
            ),
        }

    result: dict[str, Any] = {"success": False}
    continuation_activity = ref.get_continuation_activity()

    async def _callback(turn_context: TurnContext) -> None:
        outgoing = Activity(
            type="message",
            id=message_id,
            text="",
            attachments=[
                Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=card,
                )
            ],
        )
        await turn_context.update_activity(outgoing)
        result["success"] = True
        result["message_id"] = message_id

    try:
        await current_adapter.continue_conversation(bot_app_id, continuation_activity, _callback)
    except Exception as exc:
        logger.exception("Proactive card update failed for channel %s message %s", channel_id, message_id)
        result["error"] = str(exc)
    finally:
        logger.info(
            "Proactive Teams card update completed for %s/%s in %.3fs success=%s",
            channel_id,
            message_id,
            perf_counter() - started,
            result.get("success", False),
        )

    return result
