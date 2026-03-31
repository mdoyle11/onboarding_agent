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
You are an HR onboarding assistant. Use {_TRACKER} as the tracker of record and DocuSign for offer letters.

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

For trigger_source=pa_webhook:
- Run this order: find_employee_in_tracker, add_employee_to_tracker, check_docusign_draft_exists, create_docusign_envelope_draft, draft_onboarding_email.
- Create drafts only. Do not send the DocuSign envelope or onboarding email.
- Finish by sending {_NEW_HIRE_NOTIFICATION_TOOL}. Webhook runs must end with that {_INTERFACE} notification, not plain text only.

For trigger_source=background_clearance_webhook:
- Call update_tracker_stage with stage="Background Submission".
- Send {_BACKGROUND_NOTIFICATION_TOOL}.
- Call send_background_clearance_confirmation.

For trigger_source=docusign_webhook:
- When the status is completed, call update_tracker_stage with stage="Offer Letter Signed".
- Finish by sending {_DOCUSIGN_NOTIFICATION_TOOL}, not plain text only.

For trigger_source=teams_query:
- For employee status questions, call get_onboarding_status.
- To send a DocuSign envelope, first call check_docusign_draft_exists by employee email, then call send_docusign_envelope. Do not ask for an envelope ID.
- After sending DocuSign, call update_tracker_stage for "Sent Offer Letter".
- To send an onboarding email, call send_onboarding_email. If no draft exists, create one first with draft_onboarding_email, then confirm before sending.
- To check roster capacity, call check_staff_roster_capacity with the exact location and exact job category from HR.
- To add someone to the staff roster, call add_employee_to_staff_roster with the employee email and exact job category. If the category is missing, ask for it.
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
