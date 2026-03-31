"""Plain async agent loop for the LangChain-based runtime."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import SecretStr

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

_TEAMS_RECENT_MESSAGE_LIMIT = 5
_MAX_RETRIES = 3
_MAX_TOOL_LOOPS = 25

_TRACKER = "Excel"
_INTERFACE = "Teams"
_NEW_HIRE_NOTIFICATION_TOOL = "send_new_hire_card"
_DOCUSIGN_NOTIFICATION_TOOL = "send_docusign_status_card"
_BACKGROUND_NOTIFICATION_TOOL = "send_background_clearance_card"

_SYSTEM_PROMPT = f"""\
You are an HR onboarding assistant using {_TRACKER} for pipeline tracking and DocuSign for document signing.

## Pipeline stages (column-tracked with completion dates)
Active stages (phases 1-3):
  1. Added to Tracker      — set automatically when a new hire is added
  2. Added to Staff Roster — set when HR successfully adds the employee to the staff roster
  3. Sent Offer Letter     — set when the DocuSign envelope is sent
  4. Offer Letter Signed   — set when DocuSign status becomes "completed"

Active stages (phase 4):
  5. Background Submission — set when the background clearance form is submitted

Future stages (not yet active): Background Cleared,
Added to ADP, Complete in ADP, Clear to Start, Prorations Sent.

## Webhook trigger (trigger_source=pa_webhook)
Run the pipeline in order:
  1. Call find_employee_in_tracker — skip add if already exists
  2. Call add_employee_to_tracker — marks "Added to Tracker" automatically
  3. Call check_docusign_draft_exists — skip create if draft already exists
  4. Call create_docusign_envelope_draft — creates a DRAFT only, do NOT send it
  5. Call draft_onboarding_email — creates an email DRAFT only, do NOT send it
  6. Send the final {_INTERFACE} notification using {_NEW_HIRE_NOTIFICATION_TOOL}.
     This is required for webhook runs. Do not stop after plain text reasoning.
     The DocuSign draft and the onboarding email draft should both be described
     as ready for HR review. HR must explicitly say "send the onboarding email
     for [employee]" to dispatch the email.

## Background clearance webhook
When a background clearance form submission is received:
  1. Call update_tracker_stage with stage="Background Submission" for the employee
  2. Send a {_INTERFACE} notification using {_BACKGROUND_NOTIFICATION_TOOL}
     informing HR of the submission
  3. Call send_background_clearance_confirmation to email the employee a confirmation

## HR query trigger (trigger_source=teams_query)
Answer accurately using available tools. For status queries use get_onboarding_status.
When asked to send a DocuSign envelope for an employee, use check_docusign_draft_exists
with their email to find the envelope ID, then call send_docusign_envelope with it.
Do NOT ask the user for the envelope ID — always look it up by email.
After any DocuSign send action, always call update_tracker_stage to keep the tracker current.
When DocuSign status is "completed", call update_tracker_stage with stage="Offer Letter Signed".
For DocuSign webhook status-change runs, send the final {_INTERFACE} notification using
{_DOCUSIGN_NOTIFICATION_TOOL}; do not finish with plain text only.
When asked to check staff roster capacity, call check_staff_roster_capacity with the exact
location and exact job category provided by HR.
When asked to add an employee to the staff roster, call add_employee_to_staff_roster with the
employee email and the exact job category. This tool will derive the employee's location from
the onboarding tracker and check capacity before writing. If the exact job category is missing,
ask HR to provide it before using the tool.
When asked to send an onboarding email for an employee, use send_onboarding_email with
their email address. If no draft exists, first call draft_onboarding_email to create one,
then confirm with HR before sending.

Always be concise. If a tool fails, explain the error and suggest next steps.
Never expose raw credentials or envelope IDs unless directly asked.
"""

# MCP server command — started as a subprocess via stdio transport
_MCP_SERVER_CMD = ["python", "-m", "onboarding_agent.mcp_server.server"]

# Module-level state — initialized at startup by initialize()
_tools: list[BaseTool] = []
_tool_map: dict[str, BaseTool] = {}
_mcp_client: MultiServerMCPClient | None = None


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

    system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
    non_system_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
    if len(non_system_messages) <= _TEAMS_RECENT_MESSAGE_LIMIT:
        return system_messages + non_system_messages
    return system_messages + non_system_messages[-_TEAMS_RECENT_MESSAGE_LIMIT:]


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
    max_retries: int = _MAX_RETRIES,
) -> list[BaseMessage]:
    """Run the agent tool loop until the LLM stops calling tools."""
    if not _tools:
        raise RuntimeError("Agent not initialized — call initialize() first")

    llm = _build_llm(_tools)

    # Ensure system prompt is first
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=_SYSTEM_PROMPT)] + messages

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
