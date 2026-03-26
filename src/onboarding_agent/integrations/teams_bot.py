"""Microsoft 365 Agents SDK message handlers for Teams conversations."""

from __future__ import annotations

import logging
from json import JSONDecodeError, loads
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from microsoft_agents.hosting.core import TurnContext, TurnState

from onboarding_agent.agent.state import default_state
from onboarding_agent.integrations.teams_proactive import save_conversation_reference

logger = logging.getLogger(__name__)


def register_handlers(agent_app: Any) -> None:
    """Register Teams message and conversation handlers on an AgentApplication."""

    @agent_app.conversation_update("membersAdded")
    async def on_members_added(context: TurnContext, _state: TurnState) -> bool:
        save_conversation_reference(context.activity)
        return False

    @agent_app.activity("installationUpdate")
    async def on_installation_update(context: TurnContext, _state: TurnState) -> None:
        save_conversation_reference(context.activity)
        logger.info("Stored conversation reference from installationUpdate event")

    @agent_app.activity("message")
    async def on_message(context: TurnContext, _state: TurnState) -> None:
        save_conversation_reference(context.activity)

        activity = context.activity
        conversation_type = getattr(activity.conversation, "conversation_type", "") or ""
        card_action_text = _card_action_to_command(activity)

        if card_action_text:
            user_text = card_action_text
        elif conversation_type in ("channel", "groupChat"):
            if not _is_mentioned(activity):
                logger.debug("Ignoring non-mentioned message in %s", conversation_type)
                return
            user_text = _strip_mention(activity)
        else:
            user_text = (activity.text or "").strip()

        if not user_text:
            return

        from onboarding_agent.agent import graph as graph_module

        compiled = graph_module.compiled_graph
        if compiled is None:
            await context.send_activity("Agent is still starting up. Please try again shortly.")
            return

        user_id = getattr(activity.from_property, "aad_object_id", "") or ""
        channel_id = activity.channel_id or ""

        logger.info("Teams message from %s (%s): %s", user_id, conversation_type, user_text[:80])

        state = default_state()
        state["trigger_source"] = "teams_query"
        state["triggered_by_user_id"] = user_id
        state["teams_channel_id"] = channel_id
        state["messages"] = [HumanMessage(content=user_text)]

        config = {"configurable": {"thread_id": user_id or "anon"}}

        try:
            final_state: dict[str, Any] = await compiled.ainvoke(state, config)
            reply_text = "" if _should_suppress_reply(final_state) else _extract_reply(final_state)
        except Exception as exc:
            logger.exception("Graph invocation failed")
            reply_text = f"Sorry, something went wrong: {exc}"

        if reply_text:
            await context.send_activity(reply_text)


def _card_action_to_command(activity: Any) -> str:
    """Translate Adaptive Card Action.Submit payloads into plain-text commands."""
    value = getattr(activity, "value", None)
    if not isinstance(value, dict):
        return ""

    action = str(value.get("action", "")).strip().lower()
    employee_email = str(value.get("employee_email", "")).strip()
    if not action or not employee_email:
        return ""

    if action == "send_onboarding_email":
        return f"send the onboarding email for {employee_email}"
    if action == "send_docusign":
        return f"send the docusign envelope for {employee_email}"
    return ""


def _is_mentioned(activity: Any) -> bool:
    """Check if the incoming message explicitly mentions the bot."""
    bot_id = activity.recipient.id if activity.recipient else ""
    bot_name = (getattr(activity.recipient, "name", "") or "").strip().lower()
    for mention in activity.get_mentions():
        mentioned = getattr(mention, "mentioned", None)
        mentioned_id = getattr(mentioned, "id", "") if mentioned else ""
        mentioned_name = (getattr(mentioned, "name", "") if mentioned else "").strip().lower()
        mention_text = (getattr(mention, "text", "") or "").strip().lower()
        activity_text = (activity.text or "").strip().lower()

        if bot_id and mentioned_id == bot_id:
            return True
        if bot_name and mentioned_name == bot_name:
            return True
        if mention_text and bot_name and bot_name in mention_text:
            return True
        if mention_text and mention_text in activity_text:
            return True
    return False


def _strip_mention(activity: Any) -> str:
    """Remove mention text from an incoming activity."""
    text = activity.text or ""
    for mention in activity.get_mentions():
        mention_text = getattr(mention, "text", "") or ""
        if mention_text:
            text = text.replace(mention_text, "")
    return text.strip()


def _extract_reply(state: dict[str, Any]) -> str:
    """Pull the last non-system assistant text from the state messages."""
    from langchain_core.messages import AIMessage

    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts).strip()
            return str(content).strip()
    return "I was unable to complete your request."


def _should_suppress_reply(state: dict[str, Any]) -> bool:
    """Suppress duplicate assistant text only when a Teams notification tool succeeded."""
    notification_tools = {
        "send_new_hire_card",
        "send_docusign_status_card",
        "send_background_clearance_card",
        "send_teams_channel_notification",
    }
    for msg in reversed(state.get("messages", [])):
        if not isinstance(msg, ToolMessage) or msg.name not in notification_tools:
            continue
        if _tool_message_succeeded(msg):
            logger.info("Suppressing duplicate reply after successful notification tool %s", msg.name)
            return True
    return False


def _tool_message_succeeded(message: ToolMessage) -> bool:
    """Best-effort parser for MCP tool results embedded in ToolMessage content."""
    content = message.content
    if isinstance(content, str):
        return _tool_text_succeeded(content)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and _tool_text_succeeded(text):
                    return True
    return False


def _tool_text_succeeded(text: str) -> bool:
    if '"success":true' in text.lower():
        return True
    try:
        parsed = loads(text)
        if isinstance(parsed, dict):
            return bool(parsed.get("success"))
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    inner_text = item.get("text")
                    if isinstance(inner_text, str):
                        try:
                            inner = loads(inner_text)
                            if isinstance(inner, dict) and inner.get("success") is True:
                                return True
                        except JSONDecodeError:
                            continue
    except JSONDecodeError:
        return False
    return False
