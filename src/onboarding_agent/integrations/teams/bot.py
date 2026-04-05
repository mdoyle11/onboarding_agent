"""Microsoft 365 Agents SDK message handlers for Teams conversations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from microsoft_agents.hosting.core import TurnContext, TurnState

from onboarding_agent.agent import runner
from onboarding_agent.agent.runner import _decode_tool_content
from onboarding_agent.domain.identity import EmployeeIdentity
from onboarding_agent.integrations.card_state import (
    clear_new_hire_action_complete,
    delete_docusign_status_card,
    mark_new_hire_action_complete,
    refresh_docusign_status_card,
    refresh_new_hire_card,
)
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

_CARD_REFRESH_TOOL_NAMES = {
    "find_employee_in_tracker",
    "get_employee_stages",
    "get_onboarding_status",
    "update_tracker_stage",
    "clear_tracker_stage",
    "remove_employee_from_tracker",
    "check_docusign_draft_exists",
    "create_offer_letter_draft_from_tracker",
    "list_docusign_drafts",
    "delete_docusign_draft",
    "send_docusign_envelope",
    "delete_offer_letter_draft_from_tracker",
    "check_staff_roster_capacity",
    "find_employee_in_staff_roster",
    "add_employee_to_staff_roster",
    "remove_employee_from_staff_roster",
    "update_employee_in_staff_roster",
}


def _should_refresh_cards(messages: list[BaseMessage]) -> bool:
    return any(
        isinstance(message, ToolMessage) and (message.name or "").strip() in _CARD_REFRESH_TOOL_NAMES
        for message in messages
    )


async def _apply_card_side_effects_from_tool_results(messages: list[BaseMessage]) -> None:
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_name = (message.name or "").strip()
        payload = _decode_tool_content(message.content)
        if not payload.get("success"):
            continue

        employee_email = str(payload.get("employee_email", "") or "").strip()
        if not employee_email:
            continue
        submission_id = str(payload.get("submission_id", "") or "").strip()
        identity = EmployeeIdentity(
            email=employee_email,
            work_location=str(payload.get("work_location", "") or "").strip(),
            job_title=str(payload.get("job_title", "") or payload.get("position", "") or "").strip(),
            status_change=str(payload.get("status_change", "") or "").strip(),
        )
        try:
            if tool_name == "create_offer_letter_draft_from_tracker":
                await mark_new_hire_action_complete(identity, "create_docusign_draft", submission_id=submission_id)
            elif tool_name in {"delete_offer_letter_draft_from_tracker", "delete_docusign_draft"}:
                await clear_new_hire_action_complete(identity, "create_docusign_draft", submission_id=submission_id)
                await delete_docusign_status_card(identity, submission_id=submission_id)
        except Exception:
            logger.exception("Failed to apply DocuSign draft card side effects for %s", employee_email)


async def _refresh_cards_from_session_context(session_context: dict[str, Any] | None) -> None:
    if not session_context:
        return
    employee_email = str(session_context.get("employee_email", "") or "").strip()
    if not employee_email:
        return

    identity = EmployeeIdentity(
        email=employee_email,
        work_location=str(session_context.get("work_location", "") or "").strip(),
        job_title=str(session_context.get("job_title", "") or "").strip(),
        status_change=str(session_context.get("status_change", "") or "").strip(),
    )
    submission_id = str(session_context.get("submission_id", "") or "").strip()

    for refresh in (refresh_new_hire_card, refresh_docusign_status_card):
        try:
            result = await refresh(identity, submission_id=submission_id)
            if not result.get("success"):
                logger.debug("Best-effort Teams card refresh skipped for %s: %s", employee_email, result.get("error", "unknown"))
        except Exception:
            logger.exception("Best-effort Teams card refresh failed for %s", employee_email)


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
        if card_action and card_action["action"] in {"send_onboarding_email", "create_docusign_draft", "send_docusign"}:
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
            updated_session_context = await merge_session_context(
                session_key,
                runner.derive_session_context(result_messages, existing=session_context),
            )
            if _should_refresh_cards(result_messages):
                await _apply_card_side_effects_from_tool_results(result_messages)
                await _refresh_cards_from_session_context(updated_session_context)

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
            if card_action["action"] == "create_docusign_draft" and await card_action_already_completed(card_action):
                await _refresh_draft_result_surfaces(card_action)
                return
            logger.warning(
                "Deterministic Teams card action completed without a card update: action=%s employee=%s submission_id=%s message_id=%s location=%s job_title=%s status_change=%s",
                card_action["action"],
                card_action["employee_email"],
                card_action.get("submission_id", "") or "<missing>",
                card_action.get("message_id", "") or "<missing>",
                card_action.get("work_location", "") or "<missing>",
                card_action.get("job_title", "") or "<missing>",
                card_action.get("status_change", "") or "<missing>",
            )
            await notify_card_action_failure(card_action)
    except Exception:
        logger.exception(
            "Deterministic Teams card action failed: action=%s employee=%s",
            card_action["action"],
            card_action["employee_email"],
        )
        await notify_card_action_failure(card_action)


async def _refresh_draft_result_surfaces(card_action: dict[str, str]) -> None:
    identity = EmployeeIdentity(
        email=str(card_action.get("employee_email", "") or "").strip(),
        work_location=str(card_action.get("work_location", "") or "").strip(),
        job_title=str(card_action.get("job_title", "") or "").strip(),
        status_change=str(card_action.get("status_change", "") or "").strip(),
    )
    submission_id = str(card_action.get("submission_id", "") or "").strip()

    docusign_result = await refresh_docusign_status_card(identity, submission_id=submission_id)
    if docusign_result.get("success"):
        return

    root_result = await refresh_new_hire_card(identity, submission_id=submission_id)
    if not root_result.get("success"):
        logger.info(
            "Draft action fallback refresh skipped for %s: docusign=%s root=%s",
            identity.email,
            docusign_result.get("error", "unknown"),
            root_result.get("error", "unknown"),
        )
