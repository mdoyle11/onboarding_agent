"""Conversation reference store and proactive messaging for the Agents SDK."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from microsoft_agents.activity import Activity, Attachment, load_configuration_from_env, ConversationReference
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import TurnContext

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

adapter: CloudAdapter | None = None
bot_app_id: str = ""

_REFS_PATH = Path(__file__).resolve().parents[3] / "data" / "conversation_refs.json"


def _load_refs() -> dict[str, dict[str, Any]]:
    if _REFS_PATH.exists():
        try:
            return cast(dict[str, dict[str, Any]], json.loads(_REFS_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read conversation refs file, starting fresh")
    return {}


def _save_refs(refs: dict[str, dict[str, Any]]) -> None:
    _REFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REFS_PATH.write_text(json.dumps(refs, indent=2))


def _serialize_ref(ref: ConversationReference) -> dict[str, Any]:
    return cast(dict[str, Any], ref.model_dump(mode="json", by_alias=True, exclude_none=True))


def _deserialize_ref(data: dict[str, Any]) -> ConversationReference:
    return ConversationReference.model_validate(data)


def save_conversation_reference(activity: Activity) -> None:
    """Extract and store the conversation reference from an incoming activity."""
    ref = activity.get_conversation_reference()
    channel_key = ref.conversation.id if ref.conversation else ""
    if not channel_key:
        return

    refs = _load_refs()
    refs[channel_key] = _serialize_ref(ref)
    _save_refs(refs)
    logger.debug("Stored conversation reference for %s", channel_key)


def get_conversation_reference(channel_id: str) -> ConversationReference | None:
    """Look up a stored conversation reference by channel ID."""
    refs = _load_refs()

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

    has_service_connection = bool(
        settings.microsoft_app_id and settings.microsoft_app_password and settings.azure_tenant_id
    )
    if has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID",
            settings.microsoft_app_id,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET",
            settings.microsoft_app_password,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID",
            settings.azure_tenant_id,
        )
    if settings.microsoft_app_allow_anonymous or not has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__ANONYMOUS_ALLOWED",
            "true",
        )

    try:
        config = load_configuration_from_env(os.environ)
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
    current_adapter = _ensure_adapter()
    if current_adapter is None:
        return {"success": False, "error": "Cloud adapter not initialized"}

    ref = get_conversation_reference(channel_id)
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

    return result


async def update_proactive_card(
    channel_id: str,
    message_id: str,
    card: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing proactive Teams card message."""
    current_adapter = _ensure_adapter()
    if current_adapter is None:
        return {"success": False, "error": "Cloud adapter not initialized"}

    ref = get_conversation_reference(channel_id)
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

    return result
