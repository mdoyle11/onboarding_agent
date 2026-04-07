"""Outbound Teams messaging helpers."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import aiohttp

from onboarding_agent.config import settings
from onboarding_agent.integrations.graph.auth import graph_access_token

logger = logging.getLogger(__name__)


class TeamsMessenger:
    """Send Teams notifications via proactive messaging and Graph APIs."""

    async def send_channel_notification(
        self,
        channel_id: str,
        message: str,
        card: dict[str, Any] | None = None,
        session_context: dict[str, Any] | None = None,
        reply_to_id: str = "",
    ) -> dict[str, Any]:
        """Post a message to a Teams channel via Agents SDK proactive messaging."""
        started = perf_counter()
        from onboarding_agent.integrations.adaptive_cards import generic_notification_card
        from onboarding_agent.integrations.teams.memory import seed_channel_thread_context
        from onboarding_agent.integrations.teams.proactive import send_proactive_message

        if card is None:
            card = generic_notification_card(title="Onboarding Agent", message=message)
        result = await send_proactive_message(channel_id, message, card=card, reply_to_id=reply_to_id)
        if result.get("success") and result.get("message_id") and session_context:
            await seed_channel_thread_context(
                channel_id,
                str(result["message_id"]),
                session_context,
            )
        logger.info(
            "Teams channel notification to %s completed in %.3fs success=%s",
            channel_id,
            perf_counter() - started,
            result.get("success", False),
        )
        return result

    async def send_direct_message(self, user_id: str, message: str) -> dict[str, Any]:
        """Create or reuse a 1:1 chat and post a message."""
        try:
            token = await graph_access_token()
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            async with aiohttp.ClientSession() as session:
                chat_payload = {
                    "chatType": "oneOnOne",
                    "members": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_id}",
                        }
                    ],
                }
                async with session.post(
                    "https://graph.microsoft.com/v1.0/chats",
                    json=chat_payload,
                    headers=headers,
                ) as resp:
                    chat_data = await resp.json()
                    chat_id = chat_data.get("id", "")

                msg_payload = {"body": {"content": message}}
                async with session.post(
                    f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages",
                    json=msg_payload,
                    headers=headers,
                ) as resp:
                    if resp.status in (200, 201):
                        return {"success": True, "chat_id": chat_id}
                    return {"success": False, "chat_id": chat_id, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("send_direct_message failed")
            return {"success": False, "chat_id": "", "error": str(exc)}

    async def send_reply(self, activity_id: str, message: str) -> dict[str, Any]:
        """Reply in a Teams thread."""
        return await self.send_channel_notification(settings.teams_channel_id, message)
