"""Microsoft 365 Agents SDK message handlers for Teams conversations."""

from __future__ import annotations

import logging
from json import JSONDecodeError, loads
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext, TurnState

from onboarding_agent.agent.state import default_state
from onboarding_agent.integrations.adaptive_cards import new_hire_card
from onboarding_agent.integrations.card_state import (
    get_docusign_status_card,
    get_new_hire_card,
    mark_docusign_roster_complete,
    mark_new_hire_action_complete,
)
from onboarding_agent.integrations.teams_proactive import save_conversation_reference

logger = logging.getLogger(__name__)


def register_handlers(agent_app: Any) -> None:
    """Register Teams message and conversation handlers on an AgentApplication."""

    @agent_app.conversation_update("membersAdded")  # type: ignore[untyped-decorator]
    async def on_members_added(context: TurnContext, _state: TurnState) -> bool:
        save_conversation_reference(context.activity)
        return False

    @agent_app.activity("installationUpdate")  # type: ignore[untyped-decorator]
    async def on_installation_update(context: TurnContext, _state: TurnState) -> None:
        save_conversation_reference(context.activity)
        logger.info("Stored conversation reference from installationUpdate event")

    @agent_app.activity("message")  # type: ignore[untyped-decorator]
    async def on_message(context: TurnContext, _state: TurnState) -> None:
        save_conversation_reference(context.activity)

        activity = context.activity
        conversation_type = getattr(activity.conversation, "conversation_type", "") or ""
        card_action = _extract_card_action(activity)
        card_action_text = _card_action_to_command(card_action)

        if card_action_text:
            assert card_action is not None
            if _card_action_already_completed(card_action):
                await _refresh_new_hire_card(context, card_action)
                await context.send_activity(_already_completed_message(card_action))
                return
            user_text = card_action_text
        elif card_action and card_action["action"] == "add_to_staff_roster":
            await context.send_activity(
                f"Please enter the exact staff roster job category for {card_action['employee_email']} before submitting."
            )
            return
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
            if card_action and await _complete_card_action(context, card_action, final_state):
                reply_text = ""
            else:
                reply_text = "" if _should_suppress_reply(final_state) else _extract_reply(final_state)
        except Exception as exc:
            logger.exception("Graph invocation failed")
            reply_text = f"Sorry, something went wrong: {exc}"

        if reply_text:
            await context.send_activity(reply_text)


def _extract_card_action(activity: Any) -> dict[str, str] | None:
    value = getattr(activity, "value", None)
    if not isinstance(value, dict):
        return None

    action = str(value.get("action", "")).strip().lower()
    employee_email = str(value.get("employee_email", "")).strip()
    if not action or not employee_email:
        return None
    return {
        "action": action,
        "employee_email": employee_email,
        "job_category": str(value.get("job_category", "")).strip(),
    }


def _card_action_to_command(card_action: dict[str, str] | None) -> str:
    """Translate Adaptive Card Action.Submit payloads into plain-text commands."""
    if not card_action:
        return ""

    action = card_action["action"]
    employee_email = card_action["employee_email"]
    if action == "send_onboarding_email":
        return f"send the onboarding email for {employee_email}"
    if action == "send_docusign":
        return f"send the docusign envelope for {employee_email}"
    if action == "add_to_staff_roster":
        job_category = card_action.get("job_category", "").strip()
        if not job_category:
            return ""
        return f"add {employee_email} to the staff roster using the exact job category {job_category}"
    return ""


def _card_action_already_completed(card_action: dict[str, str] | None) -> bool:
    if not card_action:
        return False
    card = get_new_hire_card(card_action["employee_email"])
    if not card:
        return False
    if card_action["action"] == "send_onboarding_email":
        return bool(card.get("email_sent"))
    if card_action["action"] == "send_docusign":
        return bool(card.get("docusign_sent"))
    if card_action["action"] == "add_to_staff_roster":
        docusign_card = get_docusign_status_card(card_action["employee_email"])
        return bool(docusign_card and docusign_card.get("roster_added"))
    return False


def _already_completed_message(card_action: dict[str, str]) -> str:
    if card_action["action"] == "send_onboarding_email":
        return f"Welcome email was already sent for {card_action['employee_email']}."
    if card_action["action"] == "add_to_staff_roster":
        return f"Staff roster was already updated for {card_action['employee_email']}."
    return f"Offer letter was already sent for {card_action['employee_email']}."


async def _complete_card_action(
    context: TurnContext,
    card_action: dict[str, str],
    final_state: dict[str, Any],
) -> bool:
    action = card_action["action"]
    employee_email = card_action["employee_email"]
    if action == "send_onboarding_email":
        tool_name = "send_onboarding_email"
    elif action == "send_docusign":
        tool_name = "send_docusign_envelope"
    else:
        tool_name = "add_employee_to_staff_roster"
    if not _tool_named_succeeded(final_state, tool_name):
        return False

    if action == "add_to_staff_roster":
        docusign_card = mark_docusign_roster_complete(
            employee_email,
            card_action.get("job_category", "").strip(),
        )
        if not docusign_card:
            return False
        return await _update_docusign_status_card(context, docusign_card)

    card = mark_new_hire_action_complete(employee_email, action)
    if not card:
        return False
    return await _update_new_hire_card(context, card)


def _tool_named_succeeded(state: dict[str, Any], tool_name: str) -> bool:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, ToolMessage) and msg.name == tool_name:
            return _tool_message_succeeded(msg)
    return False


async def _refresh_new_hire_card(context: TurnContext, card_action: dict[str, str]) -> bool:
    if card_action["action"] == "add_to_staff_roster":
        card = get_docusign_status_card(card_action["employee_email"])
        if not card:
            return False
        return await _update_docusign_status_card(context, card)
    card = get_new_hire_card(card_action["employee_email"])
    if not card:
        return False
    return await _update_new_hire_card(context, card)


async def _update_new_hire_card(context: TurnContext, card: dict[str, Any]) -> bool:
    target_id = getattr(context.activity, "reply_to_id", "") or card.get("message_id", "")
    if not target_id:
        return False

    updated_card = new_hire_card(
        employee_name=card.get("employee_name", ""),
        employee_email=card.get("employee_email", ""),
        start_date=card.get("start_date", ""),
        department=card.get("department", ""),
        location=card.get("location", ""),
        manager_email=card.get("manager_email", ""),
        summary=card.get("summary", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_sent=bool(card.get("docusign_sent")),
    )
    activity = Activity(
        type="message",
        id=target_id,
        text="",
        attachments=[
            Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=updated_card,
            )
        ],
    )
    try:
        await context.update_activity(activity)
        logger.info("Updated new-hire card %s after action", target_id)
        return True
    except Exception:
        logger.exception("Failed to update new-hire card %s", target_id)
        return False


async def _update_docusign_status_card(context: TurnContext, card: dict[str, Any]) -> bool:
    target_id = getattr(context.activity, "reply_to_id", "") or card.get("message_id", "")
    if not target_id:
        return False

    from onboarding_agent.integrations.adaptive_cards import docusign_status_card

    updated_card = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
    )
    activity = Activity(
        type="message",
        id=target_id,
        text="",
        attachments=[
            Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=updated_card,
            )
        ],
    )
    try:
        await context.update_activity(activity)
        logger.info("Updated DocuSign status card %s after roster action", target_id)
        return True
    except Exception:
        logger.exception("Failed to update DocuSign status card %s", target_id)
        return False


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
