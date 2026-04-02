"""Microsoft 365 Agents SDK message handlers for Teams conversations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from microsoft_agents.hosting.core import TurnContext, TurnState

from onboarding_agent.agent import runner
from onboarding_agent.integrations.teams.card_actions import (
    already_completed_message,
    card_action_already_completed,
    execute_new_hire_card_action_without_context,
    extract_card_action,
    handle_staff_roster_card_action,
    notify_card_action_failure,
    refresh_card_from_context,
)
from onboarding_agent.integrations.teams.memory import (
    extract_context_patch_from_text,
    get_or_create_session_key,
    load_chat_history,
    merge_session_context,
    save_chat_history,
)
from onboarding_agent.integrations.teams.mentions import is_mentioned, strip_mention
from onboarding_agent.integrations.teams.proactive import save_conversation_reference
from onboarding_agent.integrations.teams.reply import extract_reply, should_suppress_reply

logger = logging.getLogger(__name__)


def register_handlers(agent_app: Any) -> None:
    """Register Teams message and conversation handlers on an AgentApplication."""

    @agent_app.conversation_update("membersAdded")  # type: ignore[untyped-decorator]
    async def on_members_added(context: TurnContext, _state: TurnState) -> bool:
        await save_conversation_reference(context.activity)
        return False

    @agent_app.activity("installationUpdate")  # type: ignore[untyped-decorator]
    async def on_installation_update(context: TurnContext, _state: TurnState) -> None:
        await save_conversation_reference(context.activity)
        logger.info("Stored conversation reference from installationUpdate event")

    @agent_app.activity("message")  # type: ignore[untyped-decorator]
    async def on_message(context: TurnContext, _state: TurnState) -> None:
        await save_conversation_reference(context.activity)

        activity = context.activity
        conversation_type = getattr(activity.conversation, "conversation_type", "") or ""
        logger.info(
            "Received Teams activity: type=%s conversation_type=%s channel_id=%s text=%r",
            getattr(activity, "type", ""),
            conversation_type,
            getattr(activity, "channel_id", "") or "",
            (activity.text or "")[:200],
        )
        card_action = extract_card_action(activity)
        if card_action and card_action["action"] == "add_to_staff_roster":
            await handle_staff_roster_card_action(context, card_action)
            return
        if card_action and card_action["action"] in {"send_onboarding_email", "send_docusign"}:
            if await card_action_already_completed(card_action):
                await refresh_card_from_context(context, card_action)
                await context.send_activity(already_completed_message(card_action))
                return
            asyncio.create_task(_run_deterministic_card_action_in_background(card_action=card_action))
            return

        if conversation_type in ("channel", "groupChat"):
            mentioned = is_mentioned(activity)
            logger.info("Channel/groupChat message mention_detected=%s", mentioned)
            if not mentioned:
                logger.debug("Ignoring non-mentioned message in %s", conversation_type)
                return
            user_text = strip_mention(activity)
        else:
            user_text = (activity.text or "").strip()

        if not user_text:
            return

        if not runner.is_ready():
            await context.send_activity("Agent is still starting up. Please try again shortly.")
            return

        user_id = getattr(activity.from_property, "aad_object_id", "") or ""
        logger.info("Teams message from %s (%s): %s", user_id, conversation_type, user_text[:80])

        # Load chat history for session continuity
        session_key = await get_or_create_session_key(activity)
        session_context = await merge_session_context(
            session_key,
            extract_context_patch_from_text(user_text),
        )
        history = await load_chat_history(session_key)
        messages: list[BaseMessage] = history + [HumanMessage(content=user_text)]

        try:
            result_messages = await runner.run_agent(
                messages,
                trigger_source="teams_query",
                session_context=session_context,
            )
            await save_chat_history(session_key, result_messages)
            await merge_session_context(
                session_key,
                runner.derive_session_context(result_messages, existing=session_context),
            )

            reply_text = (
                "" if should_suppress_reply(result_messages)
                else extract_reply(result_messages)
            )
        except Exception as exc:
            logger.exception("Agent invocation failed")
            reply_text = f"Sorry, something went wrong: {exc}"

        if reply_text:
            await context.send_activity(reply_text)
async def _run_deterministic_card_action_in_background(
    *,
    card_action: dict[str, str],
) -> None:
    try:
        updated = await execute_new_hire_card_action_without_context(card_action)
        if not updated:
            logger.warning(
                "Deterministic Teams card action completed without a card update: action=%s employee=%s",
                card_action["action"],
                card_action["employee_email"],
            )
            await notify_card_action_failure(card_action)
    except Exception:
        logger.exception(
            "Deterministic Teams card action failed: action=%s employee=%s",
            card_action["action"],
            card_action["employee_email"],
        )
        await notify_card_action_failure(card_action)
