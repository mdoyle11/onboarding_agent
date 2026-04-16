"""Lightweight production evals recorded onto OpenTelemetry traces."""

from __future__ import annotations

import ast
import json
import random
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

from onboarding_agent.config import settings
from onboarding_agent.observability.tracing import add_span_event, set_span_attributes, start_span

_CLARIFICATION_HINTS = (
    "ambiguous",
    "clarification",
    "clarify",
    "disambiguate",
    "multiple",
    "please specify",
    "specify whether",
)

_CLARIFICATION_REPLY_HINTS = (
    "?",
    "which",
    "confirm",
    "please specify",
    "specify whether",
    "provide",
    "clarify",
    "choose",
)

_FAILURE_REPLY_HINTS = (
    "could not",
    "couldn't",
    "failed",
    "failure",
    "not found",
    "unable",
    "error",
    "needs clarification",
    "please specify",
    "ambiguous",
)

_SUCCESS_CLAIMS = (
    "has been updated",
    "have been updated",
    "marked as completed",
    "marked completed",
    "successfully",
    "sent",
    "created",
    "moved",
    "removed",
    "added",
)

_WRITE_TOOL_PREFIXES = (
    "add_",
    "clear_",
    "create_",
    "delete_",
    "draft_",
    "record_",
    "remove_",
    "send_",
    "update_",
)


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    reason: str


def should_run_online_evals() -> bool:
    if not settings.evals_enabled:
        return False
    if settings.eval_sample_rate >= 1:
        return True
    if settings.eval_sample_rate <= 0:
        return False
    return random.random() <= settings.eval_sample_rate


def evaluate_agent_response(messages: list[BaseMessage], reply_text: str) -> list[EvalResult]:
    """Evaluate high-risk agent behavior from tool outputs and final response."""
    tool_events = _tool_events(messages)
    clarification_indexes = [
        index for index, event in enumerate(tool_events) if _event_requires_clarification(event)
    ]
    failures = [event for event in tool_events if _event_is_failure(event)]

    return [
        _eval_clarification_response(clarification_indexes, tool_events, reply_text),
        _eval_no_write_after_clarification(clarification_indexes, tool_events),
        _eval_failure_truthfulness(failures, reply_text),
    ]


def record_online_evals(messages: list[BaseMessage], reply_text: str) -> list[EvalResult]:
    """Run sampled evals and attach results to the current trace."""
    if not should_run_online_evals():
        return []

    results = evaluate_agent_response(messages, reply_text)
    failed = [result for result in results if not result.passed]
    with start_span(
        "agent.online_evals",
        {
            "onboarding.evals.count": len(results),
            "onboarding.evals.failed_count": len(failed),
            "onboarding.evals.failed_names": [result.name for result in failed],
        },
    ) as span:
        for result in results:
            add_span_event(
                span,
                "agent.eval_result",
                {
                    "eval.name": result.name,
                    "eval.passed": result.passed,
                    "eval.reason": result.reason,
                },
            )
        set_span_attributes(
            span,
            {
                "onboarding.evals.all_passed": not failed,
            },
        )
    return results


def _tool_events(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        payload = _decode_tool_content(message.content)
        events.append(
            {
                "tool_name": (message.name or "").strip(),
                "payload": payload,
                "content": str(message.content or ""),
            }
        )
    return events


def _decode_tool_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}
    raw = content.strip()
    if not raw:
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _event_requires_clarification(event: dict[str, Any]) -> bool:
    payload = event["payload"]
    if payload.get("needs_clarification") is True:
        return True
    if payload.get("multiple_matches") is True:
        return True
    if str(payload.get("action", "")).lower() == "needs_clarification":
        return True
    text = _event_text(event)
    return any(hint in text for hint in _CLARIFICATION_HINTS)


def _event_is_failure(event: dict[str, Any]) -> bool:
    payload = event["payload"]
    if _event_requires_clarification(event):
        return False
    if payload.get("success") is False:
        return True
    if payload.get("found") is False and not payload.get("multiple_matches"):
        return True
    text = _event_text(event)
    return text.startswith("error:") or " failed" in text or "not found" in text


def _event_text(event: dict[str, Any]) -> str:
    payload = event["payload"]
    return " ".join(
        str(part or "")
        for part in (
            event.get("content", ""),
            payload.get("error", ""),
            payload.get("summary", ""),
            payload.get("action", ""),
        )
    ).lower()


def _eval_clarification_response(
    clarification_indexes: list[int],
    tool_events: list[dict[str, Any]],
    reply_text: str,
) -> EvalResult:
    if not clarification_indexes:
        return EvalResult("clarification_response", True, "No tool result required clarification.")
    reply = reply_text.lower()
    passed = any(hint in reply for hint in _CLARIFICATION_REPLY_HINTS)
    tools = sorted({tool_events[index]["tool_name"] for index in clarification_indexes})
    return EvalResult(
        "clarification_response",
        passed,
        "Reply asked for clarification after ambiguous tool result."
        if passed
        else f"Tool result required clarification but reply did not clearly ask; tools={tools}.",
    )


def _eval_no_write_after_clarification(
    clarification_indexes: list[int],
    tool_events: list[dict[str, Any]],
) -> EvalResult:
    if not clarification_indexes:
        return EvalResult("no_write_after_clarification", True, "No clarification was required.")
    first_clarification = min(clarification_indexes)
    later_writes = [
        event["tool_name"]
        for event in tool_events[first_clarification + 1 :]
        if _is_write_tool(event["tool_name"])
    ]
    return EvalResult(
        "no_write_after_clarification",
        not later_writes,
        "No write tools ran after clarification was required."
        if not later_writes
        else f"Write tools ran after clarification was required: {later_writes}.",
    )


def _eval_failure_truthfulness(failures: list[dict[str, Any]], reply_text: str) -> EvalResult:
    if not failures:
        return EvalResult("failure_truthfulness", True, "No failed tool result was present.")
    reply = reply_text.lower()
    acknowledges_failure = any(hint in reply for hint in _FAILURE_REPLY_HINTS)
    claims_success = any(claim in reply for claim in _SUCCESS_CLAIMS)
    passed = acknowledges_failure or not claims_success
    return EvalResult(
        "failure_truthfulness",
        passed,
        "Reply acknowledged tool failure or avoided a success claim."
        if passed
        else f"Tool failed but reply appeared to claim success; tools={[event['tool_name'] for event in failures]}.",
    )


def _is_write_tool(tool_name: str) -> bool:
    return tool_name.startswith(_WRITE_TOOL_PREFIXES)
