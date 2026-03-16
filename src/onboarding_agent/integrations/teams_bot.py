"""Teams ActivityHandler — receives messages from the Bot Framework, invokes the graph."""

from __future__ import annotations

import logging
from typing import Any

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity
from langchain_core.messages import HumanMessage

from onboarding_agent.agent.state import default_state

logger = logging.getLogger(__name__)


class OnboardingBot(ActivityHandler):
    """Receives Teams messages and routes them through the LangGraph agent."""

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        # Import here to avoid circular import at module load time
        from onboarding_agent.agent import graph as graph_module

        compiled = graph_module.compiled_graph
        if compiled is None:
            await turn_context.send_activity("Agent is still starting up. Please try again shortly.")
            return

        user_text: str = turn_context.activity.text or ""
        user_id: str = getattr(turn_context.activity.from_property, "aad_object_id", "") or ""
        channel_id: str = turn_context.activity.channel_id or ""

        logger.info("Teams message from %s: %s", user_id, user_text[:80])

        state = default_state()
        state["trigger_source"] = "teams_query"
        state["triggered_by_user_id"] = user_id
        state["teams_channel_id"] = channel_id
        state["messages"] = [HumanMessage(content=user_text)]

        config = {"configurable": {"thread_id": user_id or "anon"}}

        try:
            final_state: dict[str, Any] = await compiled.ainvoke(state, config)
            # Extract the last AI message as the reply
            reply_text = _extract_reply(final_state)
        except Exception as exc:
            logger.exception("Graph invocation failed")
            reply_text = f"Sorry, something went wrong: {exc}"

        await turn_context.send_activity(Activity(type="message", text=reply_text))


def _extract_reply(state: dict[str, Any]) -> str:
    """Pull the last non-system assistant text from the state messages."""
    from langchain_core.messages import AIMessage

    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                # Handle list-form content (text blocks)
                parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts).strip()
            return str(content).strip()
    return "I was unable to complete your request."
