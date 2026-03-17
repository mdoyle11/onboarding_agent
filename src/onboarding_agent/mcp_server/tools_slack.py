"""Slack notification tools — channel posts, DMs, and thread replies."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from slack_sdk.web.async_client import AsyncWebClient

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)


def _client() -> AsyncWebClient:
    return AsyncWebClient(token=settings.slack_bot_token)


def register(mcp: FastMCP) -> None:
    """Register all Slack notification tools on the given FastMCP instance."""

    @mcp.tool()
    async def send_slack_channel_notification(channel_id: str, message: str) -> dict[str, Any]:
        """
        Post a message to a Slack channel.

        Parameters:
        - channel_id: Slack channel ID (e.g. "C012AB3CD") or name (e.g. "#hr-onboarding")
        - message: Message text (plain text or Slack mrkdwn)

        Returns a dict with:
        - success (bool)
        - message_ts (str) — Slack message timestamp, usable as thread_ts for replies
        """
        try:
            resp = await _client().chat_postMessage(channel=channel_id, text=message)
            return {"success": resp["ok"], "message_ts": resp.get("ts", "")}
        except Exception as exc:
            logger.exception("send_slack_channel_notification failed")
            return {"success": False, "message_ts": "", "error": str(exc)}

    @mcp.tool()
    async def send_slack_direct_message(user_id: str, message: str) -> dict[str, Any]:
        """
        Send a Slack direct message to a user.

        Parameters:
        - user_id: Slack user ID (e.g. "U012AB3CD")
        - message: Message text

        Returns a dict with:
        - success (bool)
        - channel_id (str) — the DM channel ID
        """
        try:
            client = _client()
            # Open a DM channel then post
            open_resp = await client.conversations_open(users=user_id)
            dm_channel = open_resp["channel"]["id"]
            post_resp = await client.chat_postMessage(channel=dm_channel, text=message)
            return {"success": post_resp["ok"], "channel_id": dm_channel}
        except Exception as exc:
            logger.exception("send_slack_direct_message failed")
            return {"success": False, "channel_id": "", "error": str(exc)}

    @mcp.tool()
    async def send_slack_reply(channel_id: str, thread_ts: str, message: str) -> dict[str, Any]:
        """
        Reply in an existing Slack thread.

        Parameters:
        - channel_id: The Slack channel containing the thread
        - thread_ts: The timestamp of the parent message (from send_slack_channel_notification)
        - message: Reply text

        Returns a dict with success (bool).
        """
        try:
            resp = await _client().chat_postMessage(
                channel=channel_id, thread_ts=thread_ts, text=message
            )
            return {"success": resp["ok"]}
        except Exception as exc:
            logger.exception("send_slack_reply failed")
            return {"success": False, "error": str(exc)}
