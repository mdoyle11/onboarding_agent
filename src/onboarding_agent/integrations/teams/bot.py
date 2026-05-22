"""Microsoft 365 Agents SDK message handlers for Teams conversations."""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from microsoft_agents.activity import Activity, Attachment
from microsoft_agents.hosting.core import TurnContext, TurnState

from onboarding_agent.agent import runner
from onboarding_agent.agent.runner import _decode_tool_content
from onboarding_agent.config import settings
from onboarding_agent.domain.identity import EmployeeIdentity
from onboarding_agent.integrations.card_state import (
    clear_new_hire_action_complete,
    delete_docusign_status_card,
    mark_new_hire_action_complete,
    refresh_docusign_status_card,
    refresh_new_hire_card,
    refresh_separation_card,
)
from onboarding_agent.integrations.teams.card_actions import (
    already_completed_message,
    card_action_already_completed,
    execute_new_hire_card_action_without_context,
    extract_card_action,
    handle_clear_to_start_card_action,
    handle_separation_card_action,
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
from onboarding_agent.observability.evals import record_online_evals
from onboarding_agent.observability.pii import identifier_attributes, redact_text
from onboarding_agent.observability.tracing import set_span_attributes, start_span

logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

_SLASH_COMMAND_HELP = """\
**Onboarding Agent Help**

**Status And Lookup**
- `/status <email>` - Check onboarding status.
- `/stages <email>` - Show tracker stages.
- `/find-tracker <email>` - Find an onboarding tracker row.
- `/find-roster <email> <location>` - Find a staff roster row.

*Examples*
- `/status employee@example.com`
- `/find-roster employee@example.com Collier`

**Staff Roster**
- `/capacity <location> <group>` - Check one group's capacity.
- `/vacancies <location>` - List groups below capacity.
- `/leave <email> <start|end>` - Start or end leave status.

*Examples*
- `/capacity Collier Teacher`
- `/vacancies Collier`
- `/leave employee@example.com start`

**Updates**
- `/update-field <tracker|roster> <email> <column> <value>` - Update a non-stage field.
- `/update-stage <email> <stage> <complete|incomplete>` - Complete or clear a tracker stage.
- `/clear-stage <email> <stage>` - Clear a tracker stage.
- `/clear-to-start <email> [submission_id]` - Open the Clear to Start email form.

*Examples*
- `/update-field tracker employee@example.com "Requested Start Date" "2026-08-03"`
- `/update-field roster employee@example.com "Grade Level" "3"`
- `/update-stage employee@example.com "Background Submission" complete`
- `/clear-stage employee@example.com "Background Submission"`
- `/clear-to-start employee@example.com`

**DocuSign**
- `/drafts` - List unsent DocuSign drafts.

**Natural Language Examples**
- `Is employee@example.com clear to start?`
- `Mark Background Submission complete for employee@example.com submission ID 143.`
- `Move employee@example.com to the Separations sheet as Transfer Out.`
"""


def _expand_slash_command(user_text: str) -> tuple[bool, str]:
    text = user_text.strip()
    if not text.startswith("/"):
        return False, text

    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    if not parts:
        return False, text

    command = parts[0].lstrip("/").lower()
    args = parts[1:]
    if command in {"help", "?"}:
        return True, _SLASH_COMMAND_HELP
    if command == "status":
        if not args:
            return True, "Usage: /status <email>"
        return False, f"Get onboarding status for {args[0]}."
    if command == "stages":
        if not args:
            return True, "Usage: /stages <email>"
        return False, f"Show tracker stages for {args[0]}."
    if command == "capacity":
        if len(args) < 2:
            return True, "Usage: /capacity <location> <group>"
        location = args[0]
        group = " ".join(args[1:])
        return False, f"Check staff roster capacity at {location} for group {group}."
    if command == "vacancies":
        if not args:
            return True, "Usage: /vacancies <location>"
        return False, f"List staff roster vacancies at {' '.join(args)}."
    if command in {"find-roster", "roster"}:
        if len(args) < 2:
            return True, "Usage: /find-roster <email> <location>"
        return False, f"Find {args[0]} in the staff roster at {' '.join(args[1:])}."
    if command in {"find-tracker", "tracker"}:
        if not args:
            return True, "Usage: /find-tracker <email>"
        return False, f"Find {args[0]} in the onboarding tracker."
    if command == "drafts":
        if args:
            return True, "Usage: /drafts"
        return False, "List unsent DocuSign drafts waiting to be sent."
    if command == "leave":
        if len(args) < 2:
            return True, "Usage: /leave <email> <start|end>"
        employee = args[0]
        action = args[1].lower()
        if action in {"start", "on", "begin"}:
            return False, f"Update staff roster leave status for {employee} to On Leave."
        if action in {"end", "off", "return", "returned"}:
            return False, f"Update staff roster leave status for {employee} to Active."
        return True, "Usage: /leave <email> <start|end>"
    if command == "clear-stage":
        if len(args) < 2:
            return True, 'Usage: /clear-stage <email> <stage>\nExample: /clear-stage employee@example.com "Background Submission"'
        employee = args[0]
        stage = " ".join(args[1:])
        return False, f"Clear tracker stage '{stage}' for {employee} so it is blank."
    if command == "update-field":
        if len(args) < 4:
            return True, 'Usage: /update-field <tracker|roster> <email> <column> <value>\nExample: /update-field tracker employee@example.com "Requested Start Date" "2026-08-03"'
        target = args[0].lower()
        if target not in {"tracker", "roster"}:
            return True, "Usage: /update-field <tracker|roster> <email> <column> <value>"
        employee = args[1]
        column = args[2]
        value = " ".join(args[3:])
        tool_name = "update_tracker_field" if target == "tracker" else "update_staff_roster_field"
        return False, f"Use {tool_name} to update the {target} field '{column}' for {employee} to '{value}'. This is not a tracker stage update."
    if command == "update-stage":
        if len(args) < 3:
            return True, 'Usage: /update-stage <email> <stage> <complete|incomplete>\nExample: /update-stage employee@example.com "Background Submission" complete'
        employee = args[0]
        action = args[-1].lower()
        stage = " ".join(args[1:-1])
        if action in {"complete", "completed", "done"}:
            return False, f"Mark tracker stage '{stage}' complete for {employee}."
        if action in {"incomplete", "clear", "blank", "pending", "undo"}:
            return False, f"Clear tracker stage '{stage}' for {employee} so it is blank."
        return True, "Usage: /update-stage <email> <stage> <complete|incomplete>"

    return True, f"Unknown command '/{command}'.\n\n{_SLASH_COMMAND_HELP}"


def _activity_identifier_attrs(activity: Any) -> dict[str, str]:
    return identifier_attributes(
        teams_conversation_id=getattr(getattr(activity, "conversation", None), "id", "") or "",
        teams_user_id=getattr(getattr(activity, "from_property", None), "aad_object_id", "") or "",
        salt=settings.trace_hash_salt,
    )


def _card_action_trace_attrs(activity: Any, card_action: dict[str, str]) -> dict[str, Any]:
    return {
        "onboarding.route": "card_action",
        "onboarding.card.action": card_action.get("action", ""),
        "onboarding.card.has_message_id": bool(card_action.get("message_id")),
        "onboarding.card.has_submission_id": bool(card_action.get("submission_id")),
        **identifier_attributes(
            employee_email=card_action.get("employee_email", ""),
            submission_id=card_action.get("submission_id", ""),
            teams_conversation_id=getattr(getattr(activity, "conversation", None), "id", "") or "",
            teams_user_id=getattr(getattr(activity, "from_property", None), "aad_object_id", "") or "",
            salt=settings.trace_hash_salt,
        ),
    }


def _parse_clear_to_start_command(user_text: str) -> tuple[bool, list[str], str]:
    try:
        parts = shlex.split(user_text.strip())
    except ValueError:
        parts = user_text.strip().split()
    if not parts or parts[0].lstrip("/").lower() not in {"clear-to-start", "clearstart"}:
        return False, [], ""
    if len(parts) < 2:
        return True, [], "Usage: /clear-to-start <email> [submission_id]"
    args = parts[1:]
    if len(args) >= 4 and args[1].lower() == "submission" and args[2].lower() == "id":
        return True, [args[0], args[3]], ""
    if len(args) >= 3 and args[1].lower() in {"submission-id", "submission_id"}:
        return True, [args[0], args[2]], ""
    if len(args) >= 3 and args[1].lower() == "id":
        return True, [args[0], args[2]], ""
    return True, args, ""


async def _send_clear_to_start_card_from_command(context: TurnContext, args: list[str]) -> str:
    from onboarding_agent.integrations.adaptive_cards import clear_to_start_card
    from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

    employee_email = args[0]
    if not _EMAIL_RE.match(employee_email):
        return (
            "Clear-to-start requires the employee's full email address. "
            f"Received `{employee_email}`."
        )
    submission_id = args[1] if len(args) > 1 else ""
    tracker_record = await TrackerClient().find_employee_in_tracker(
        employee_email,
        submission_id=submission_id,
    )
    if not tracker_record.get("found"):
        return str(tracker_record.get("error") or f"No tracker row found for {employee_email}.")

    employee_name = str(tracker_record.get("name", "") or tracker_record.get("staff_name", "") or employee_email)
    work_location = str(tracker_record.get("location", "") or tracker_record.get("work_location", "") or "")
    job_title = str(tracker_record.get("job_title", "") or tracker_record.get("position", "") or "")
    status_change = str(tracker_record.get("status_change", "") or "")
    requested_start_date = str(tracker_record.get("start_date", "") or tracker_record.get("requested_start_date", "") or "")
    resolved_submission_id = str(tracker_record.get("submission_id", "") or submission_id or "")
    requesting_manager = str(tracker_record.get("requesting_manager", "") or tracker_record.get("manager_name", "") or "")

    card = clear_to_start_card(
        employee_email=employee_email,
        employee_name=employee_name,
        submission_id=resolved_submission_id,
        work_location=work_location,
        job_title=job_title,
        status_change=status_change,
        requested_start_date=requested_start_date,
        requesting_manager=requesting_manager,
    )
    await context.send_activity(
        Activity(
            type="message",
            text="",
            attachments=[
                Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=card,
                )
            ],
        )
    )
    return ""


_CARD_REFRESH_TOOL_NAMES = {
    "find_employee_in_tracker",
    "get_employee_stages",
    "get_onboarding_status",
    "update_tracker_stage",
    "update_tracker_field",
    "clear_tracker_stage",
    "remove_employee_from_tracker",
    "check_docusign_draft_exists",
    "create_offer_letter_draft_from_tracker",
    "list_docusign_drafts",
    "delete_docusign_draft",
    "send_docusign_envelope",
    "delete_offer_letter_draft_from_tracker",
    "check_staff_roster_capacity",
    "list_staff_roster_vacancies",
    "find_employee_in_staff_roster",
    "add_employee_to_staff_roster",
    "remove_employee_from_staff_roster",
    "update_employee_in_staff_roster",
    "update_staff_roster_field",
    "record_separation",
    "find_separation_record",
    "update_leave_status",
}


def _is_synthetic_loadtest_activity(activity: Any) -> bool:
    if not settings.teams_loadtest_mode:
        return False
    activity_id = str(getattr(activity, "id", "") or "").strip()
    conversation_id = str(getattr(getattr(activity, "conversation", None), "id", "") or "").strip()
    from_property = getattr(activity, "from_property", None)
    user_id = str(getattr(from_property, "aad_object_id", "") or getattr(from_property, "id", "") or "").strip()
    return (
        activity_id.startswith("loadtest-activity-")
        or conversation_id.startswith("loadtest-conv-")
        or user_id.startswith("loadtest-user-")
    )


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

    for refresh in (refresh_new_hire_card, refresh_docusign_status_card, refresh_separation_card):
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
        synthetic_loadtest = _is_synthetic_loadtest_activity(activity)
        conversation_type = getattr(activity.conversation, "conversation_type", "") or ""
        logger.info(
            "Received Teams activity: type=%s conversation_type=%s channel_id=%s text=%r",
            getattr(activity, "type", ""),
            conversation_type,
            getattr(activity, "channel_id", "") or "",
            (activity.text or "")[:200],
        )
        card_action = extract_card_action(activity)
        if card_action and card_action["action"] == "send_clear_to_start":
            with start_span(
                "teams.card_action.send_clear_to_start",
                _card_action_trace_attrs(activity, card_action),
            ):
                await handle_clear_to_start_card_action(context, card_action)
            return
        if card_action and card_action["action"] == "add_to_staff_roster":
            with start_span(
                "teams.card_action.add_to_staff_roster",
                _card_action_trace_attrs(activity, card_action),
            ):
                await handle_staff_roster_card_action(context, card_action)
            return
        if card_action and card_action["action"] in {"record_separation", "update_leave_start", "update_leave_end"}:
            with start_span(
                f"teams.card_action.{card_action['action']}",
                _card_action_trace_attrs(activity, card_action),
            ):
                if await card_action_already_completed(card_action):
                    await refresh_card_from_context(context, card_action)
                    await context.send_activity(already_completed_message(card_action))
                    return
                await handle_separation_card_action(context, card_action)
            return
        if card_action and card_action["action"] in {"send_onboarding_email", "create_docusign_draft", "refresh_review_link", "send_docusign"}:
            with start_span(
                f"teams.card_action.{card_action['action']}",
                _card_action_trace_attrs(activity, card_action),
            ):
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

        is_clear_to_start_command, clear_to_start_args, clear_to_start_usage = _parse_clear_to_start_command(user_text)
        if is_clear_to_start_command:
            with start_span(
                "teams.slash_command.clear_to_start",
                {
                    "onboarding.route": "slash_command",
                    "onboarding.command": "clear-to-start",
                    "onboarding.synthetic_loadtest": synthetic_loadtest,
                    "onboarding.command_text": redact_text(
                        user_text,
                        salt=settings.trace_hash_salt,
                        capture_full_payloads=settings.trace_capture_full_payloads,
                    ),
                    **_activity_identifier_attrs(activity),
                },
            ):
                if not synthetic_loadtest:
                    if clear_to_start_usage:
                        await context.send_activity(clear_to_start_usage)
                    else:
                        result_text = await _send_clear_to_start_card_from_command(context, clear_to_start_args)
                        if result_text:
                            await context.send_activity(result_text)
            return

        slash_handled, slash_result = _expand_slash_command(user_text)
        if slash_handled:
            with start_span(
                "teams.slash_command.expand",
                {
                    "onboarding.route": "slash_command",
                    "onboarding.synthetic_loadtest": synthetic_loadtest,
                    "onboarding.command_text": redact_text(
                        user_text,
                        salt=settings.trace_hash_salt,
                        capture_full_payloads=settings.trace_capture_full_payloads,
                    ),
                    **_activity_identifier_attrs(activity),
                },
            ):
                if not synthetic_loadtest:
                    await context.send_activity(slash_result)
            return
        user_text = slash_result

        if not runner.is_ready():
            if synthetic_loadtest:
                logger.info("Skipping reply for synthetic Teams load-test activity while agent is starting")
                return
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
            with start_span(
                "teams.agent_query",
                {
                    "onboarding.route": "natural_language",
                    "onboarding.synthetic_loadtest": synthetic_loadtest,
                    "onboarding.user_text": redact_text(
                        user_text,
                        salt=settings.trace_hash_salt,
                        capture_full_payloads=settings.trace_capture_full_payloads,
                    ),
                    **identifier_attributes(
                        employee_email=str(session_context.get("employee_email", "") or ""),
                        submission_id=str(session_context.get("submission_id", "") or ""),
                        teams_conversation_id=getattr(getattr(activity, "conversation", None), "id", "") or "",
                        teams_user_id=user_id,
                        salt=settings.trace_hash_salt,
                    ),
                },
            ) as span:
                result_messages = await runner.run_agent(
                    messages,
                    trigger_source="teams_query",
                    session_context=session_context,
                )
                set_span_attributes(
                    span,
                    {
                        "onboarding.result_message_count": len(result_messages),
                        "onboarding.reply_suppressed": should_suppress_reply(result_messages),
                    },
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
            record_online_evals(result_messages, reply_text)
        except Exception as exc:
            logger.exception("Agent invocation failed")
            reply_text = f"Sorry, something went wrong: {exc}"

        if reply_text and not synthetic_loadtest:
            await context.send_activity(reply_text)
        elif reply_text:
            logger.info(
                "Skipping final reply send for synthetic Teams load-test activity: conversation_id=%s activity_id=%s",
                getattr(getattr(activity, "conversation", None), "id", "") or "",
                getattr(activity, "id", "") or "",
            )


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
