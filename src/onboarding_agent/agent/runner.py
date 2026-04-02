"""Plain async agent loop for the LangChain-based runtime."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
import os
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import SecretStr

from onboarding_agent.agent.session_context import SESSION_CONTEXT_FIELDS
from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_TEAMS_RECENT_MESSAGE_LIMIT = 4
_MAX_RETRIES = 3
_MAX_TOOL_LOOPS = 25

_SYSTEM_PROMPT = """\
You are an HR onboarding assistant. Use Excel as the tracker of record and DocuSign for offer letters.

Core rules:
- Be concise.
- Use tools whenever the answer depends on tracker, roster, email, or DocuSign data.
- Preserve any user-provided email exactly as written when calling tools.
- If required data is missing, ask a short clarification question.
- If a tool fails, explain the failure and next step.
- Never expose credentials. Do not expose envelope IDs unless directly asked.

Tracked stages:
- Added to Tracker
- Added to Staff Roster
- Sent Offer Letter
- Offer Letter Signed
- Background Submission
- Background Cleared
- Added to ADP
- Employee Complete ADP Profile
- Complete in ADP
- Proration
- Clear to Start
- Drug Screening

For trigger_source=teams_query:
- For employee status questions, call get_onboarding_status.
- HR users can update any tracker stage through natural language.
- To mark a stage complete, call update_tracker_stage. If no date/value is specified, leave stage_value empty so the tool uses today's date.
- If the user gives an explicit date or value such as "N/A", pass that as stage_value.
- To clear or reset a stage back to pending, call clear_tracker_stage.
- For offer-letter actions, never guess between multiple tracker rows that share the same email unless exactly one matching row still needs an offer letter.
- If work_location, job_title, or status_change are available from the user or session context, pass them into relevant tools.
- If only an email is provided and the employee may have multiple tracker rows, resolve or ask for clarification before sending DocuSign.
- To send a DocuSign envelope, first call check_docusign_draft_exists with the fullest available identity, then call send_docusign_envelope. Do not ask for an envelope ID.
- After sending DocuSign, call update_tracker_stage for "Sent Offer Letter" using the same identity fields.
- To send an onboarding email, call send_onboarding_email. If no draft exists, create one first with draft_onboarding_email, then confirm before sending.
- For staff roster capacity, use the exact Group value used in the roster/capacity sheets. Do not assume categories like Instructional, Administrative, or Support unless the workbook actually uses them.
- If the user asks for capacity for a title like "teacher" and it appears to be the intended Group value, call check_staff_roster_capacity directly with that value.
- If work_location is available from the user or session context, use it for roster capacity queries instead of asking again.
- To add someone to the staff roster, call add_employee_to_staff_roster with the employee email and exact job category/Group value. If the category is missing, ask for it.
"""

# MCP server command — started as a subprocess via stdio transport
_MCP_SERVER_CMD = ["python", "-m", "onboarding_agent.mcp_server.server"]

# Module-level state — initialized at startup by initialize()
_tools: list[BaseTool] = []
_tool_map: dict[str, BaseTool] = {}
_mcp_client: MultiServerMCPClient | None = None


def _format_session_context(session_context: dict[str, Any] | None) -> SystemMessage | None:
    """Render compact structured session state as a small system message."""
    if not session_context:
        return None

    fields = [(name, session_context.get(name, "")) for name in SESSION_CONTEXT_FIELDS if name != "last_updated_at"]
    lines = [f"- {name}: {value}" for name, value in fields if value not in ("", None)]
    if not lines:
        return None

    return SystemMessage(
        content=(
            "Current session context:\n"
            + "\n".join(lines)
            + "\nUse this to preserve continuity when the current request is ambiguous."
        )
    )


def _decode_tool_content(content: Any) -> dict[str, Any]:
    """Best-effort decode of ToolMessage content into a dict."""
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
            return cast(dict[str, Any], parsed)
    logger.debug("Could not decode tool content as dict: %s", raw[:200])
    return {}


def derive_session_context(
    messages: list[BaseMessage],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive compact reusable session context from recent tool results."""
    context: dict[str, Any] = dict(existing or {})

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue

        payload = _decode_tool_content(message.content)
        if not payload:
            continue

        tool_name = (message.name or "").strip()

        if tool_name in {
            "find_employee_in_tracker",
            "get_employee_stages",
            "get_onboarding_status",
            "draft_onboarding_email",
            "send_onboarding_email",
            "check_docusign_draft_exists",
            "add_employee_to_staff_roster",
        }:
            employee_email = str(
                payload.get("employee_email")
                or payload.get("email")
                or ""
            ).strip()
            if employee_email:
                context["employee_email"] = employee_email
            work_location = str(payload.get("work_location") or payload.get("location") or "").strip()
            if work_location:
                context["work_location"] = work_location
            job_title = str(payload.get("job_title") or payload.get("position") or "").strip()
            if job_title:
                context["job_title"] = job_title
            status_change = str(payload.get("status_change") or "").strip()
            if status_change:
                context["status_change"] = status_change

        if tool_name in {"get_employee_stages", "get_onboarding_status"}:
            employee_name = str(payload.get("name", "")).strip()
            if employee_name:
                context["employee_name"] = employee_name
            context["intent"] = "check_onboarding_status"

        if tool_name in {"draft_onboarding_email", "send_onboarding_email"}:
            context["intent"] = "send_onboarding_email"
            if tool_name == "draft_onboarding_email" and payload.get("success"):
                context["pending_confirmation"] = True
            if tool_name == "send_onboarding_email" and payload.get("success"):
                context["pending_confirmation"] = False

        if tool_name in {"check_docusign_draft_exists", "create_docusign_envelope_draft", "send_docusign_envelope"}:
            envelope_id = str(payload.get("envelope_id", "")).strip()
            if envelope_id:
                context["envelope_id"] = envelope_id
            context["intent"] = "send_docusign_envelope"

        if tool_name == "get_docusign_envelope_status":
            envelope_id = str(payload.get("envelope_id", "")).strip()
            if envelope_id:
                context["envelope_id"] = envelope_id

        if tool_name == "add_employee_to_staff_roster":
            job_category = str(payload.get("job_category", "")).strip()
            if job_category:
                context["job_category"] = job_category
            context["intent"] = "staff_roster"

    return context


async def initialize() -> None:
    """Load MCP tools via stdio transport. Call once at application startup."""
    global _tools, _tool_map, _mcp_client

    logger.info("Connecting to MCP server via stdio…")
    client = MultiServerMCPClient(
        {
            "onboarding": {
                "command": _MCP_SERVER_CMD[0],
                "args": _MCP_SERVER_CMD[1:],
                "cwd": os.getcwd(),
                "env": dict(os.environ),
                "transport": "stdio",
            }
        }
    )
    _mcp_client = client
    _tools = await client.get_tools()
    _tool_map = {t.name: t for t in _tools}
    logger.info("Loaded %d MCP tools: %s", len(_tools), list(_tool_map))


def is_ready() -> bool:
    """Return True if the agent has been initialized with MCP tools."""
    return bool(_tools)


def _build_llm(tools: list[Any]) -> Any:
    if settings.is_gemini():
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
        ).bind_tools(tools)

    from langchain_anthropic import ChatAnthropic
    chat_anthropic_cls: Any = ChatAnthropic
    anthropic_llm: Any = chat_anthropic_cls(
        model="claude-sonnet-4-6",
        api_key=SecretStr(settings.anthropic_api_key),
        max_tokens=4096,
    )
    return anthropic_llm.bind_tools(tools)


def _trim_messages(messages: list[BaseMessage], trigger_source: str) -> list[BaseMessage]:
    """Bound conversational memory for Teams queries while keeping webhook runs intact."""
    if trigger_source != "teams_query":
        return messages

    system_messages: list[BaseMessage] = [
        msg for msg in messages if isinstance(msg, SystemMessage)
    ]
    conversational_messages: list[BaseMessage] = [
        msg for msg in messages if isinstance(msg, (HumanMessage, AIMessage))
    ]
    if len(conversational_messages) <= _TEAMS_RECENT_MESSAGE_LIMIT:
        return system_messages + conversational_messages
    return system_messages + conversational_messages[-_TEAMS_RECENT_MESSAGE_LIMIT:]


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_map: dict[str, BaseTool],
) -> list[ToolMessage]:
    """Execute all tool calls in parallel and return ToolMessages."""

    async def _run_tool(tool_call: dict[str, Any]) -> ToolMessage:
        name = str(tool_call["name"])
        args = cast(dict[str, Any], tool_call["args"])
        call_id = str(tool_call["id"])

        if name not in tool_map:
            return ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id, name=name)
        try:
            tool = tool_map[name]
            logger.info("Executing tool %s with args=%s", name, args)
            result = (
                await tool.arun(args)
                if inspect.iscoroutinefunction(tool.arun)
                else tool.run(args)
            )
            logger.info("Tool %s result=%s", name, result)
            return ToolMessage(content=str(result), tool_call_id=call_id, name=name)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return ToolMessage(content=f"Error: {exc}", tool_call_id=call_id, name=name)

    return list(await asyncio.gather(*[_run_tool(tc) for tc in tool_calls]))


async def run_agent(
    messages: list[BaseMessage],
    *,
    trigger_source: str = "",
    session_context: dict[str, Any] | None = None,
    max_retries: int = _MAX_RETRIES,
) -> list[BaseMessage]:
    """Run the agent tool loop until the LLM stops calling tools."""
    if not _tools:
        raise RuntimeError("Agent not initialized — call initialize() first")

    llm = _build_llm(_tools)

    # Ensure system prompt is first
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=_SYSTEM_PROMPT)] + messages

    context_message = _format_session_context(session_context)
    if context_message is not None:
        messages = [messages[0], context_message, *messages[1:]]

    # Trim for Teams queries
    messages = _trim_messages(messages, trigger_source)

    for attempt in range(max_retries):
        try:
            for _ in range(_MAX_TOOL_LOOPS):
                response = cast(AIMessage, await llm.ainvoke(messages))
                messages.append(response)
                logger.info(
                    "Agent response for %s: tool_calls=%d content=%s",
                    trigger_source or "unknown",
                    len(response.tool_calls),
                    response.content,
                )

                if not response.tool_calls:
                    return messages

                tool_results = await _execute_tool_calls(response.tool_calls, _tool_map)
                messages.extend(tool_results)

            # Safety: if we hit the tool loop limit, return what we have
            logger.warning("Agent hit tool loop limit (%d iterations)", _MAX_TOOL_LOOPS)
            return messages

        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning("Agent attempt %d failed: %s", attempt + 1, exc)

    return messages
