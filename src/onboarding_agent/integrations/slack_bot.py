"""Slack bot — receives messages via Socket Mode, invokes the LangGraph agent."""

from __future__ import annotations

import logging
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from langchain_core.messages import HumanMessage

from onboarding_agent.agent.state import default_state
from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

# Module-level app + handler — initialised by create_slack_handler()
slack_app: AsyncApp | None = None
socket_handler: AsyncSocketModeHandler | None = None


def create_slack_handler() -> AsyncSocketModeHandler:
    """Build the Slack AsyncApp and Socket Mode handler. Called once at startup."""
    global slack_app, socket_handler

    slack_app = AsyncApp(token=settings.slack_bot_token)

    @slack_app.event("app_mention")
    async def handle_mention(event: dict[str, Any], say: Any) -> None:
        await _handle_message(event, say)

    @slack_app.event("message")
    async def handle_dm(event: dict[str, Any], say: Any) -> None:
        # Only handle DMs (channel_type=im) to avoid double-processing channel mentions
        if event.get("channel_type") == "im":
            await _handle_message(event, say)

    socket_handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    return socket_handler


async def _handle_message(event: dict[str, Any], say: Any) -> None:
    """Route an incoming Slack message through the LangGraph agent and reply."""
    from onboarding_agent.agent import graph as graph_module

    compiled = graph_module.compiled_graph
    if compiled is None:
        await say("Agent is still starting up. Please try again shortly.")
        return

    # Strip bot mention prefix if present (<@BOTID> text)
    text: str = event.get("text", "")
    if "<@" in text:
        text = text.split(">", 1)[-1].strip()

    user_id: str = event.get("user", "")
    channel_id: str = event.get("channel", "")
    thread_ts: str = event.get("thread_ts") or event.get("ts", "")

    logger.info("Slack message from %s: %s", user_id, text[:80])

    state = default_state()
    state["trigger_source"] = "teams_query"   # reuse existing trigger label
    state["triggered_by_user_id"] = user_id
    state["teams_channel_id"] = channel_id    # reused for routing
    state["messages"] = [HumanMessage(content=text)]

    config = {"configurable": {"thread_id": f"slack-{user_id or 'anon'}"}}

    try:
        final_state: dict[str, Any] = await compiled.ainvoke(state, config)
        reply = _extract_reply(final_state)
    except Exception as exc:
        logger.exception("Graph invocation failed")
        reply = f"Sorry, something went wrong: {exc}"

    await say(text=reply, thread_ts=thread_ts)


def _extract_reply(state: dict[str, Any]) -> str:
    from langchain_core.messages import AIMessage

    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts).strip()
            return str(content).strip()
    return "I was unable to complete your request."
