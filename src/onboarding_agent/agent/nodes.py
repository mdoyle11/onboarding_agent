"""Node functions for the onboarding LangGraph."""

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from onboarding_agent.agent.state import OnboardingState
from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

# Tracker label for the system prompt
_TRACKER = "Google Sheets" if settings.is_sheets() else "Excel"
_INTERFACE = settings.chat_interface.capitalize()

# System prompt shared across all invocations
_SYSTEM_PROMPT = f"""\
You are an HR onboarding assistant using {_TRACKER} for pipeline tracking and DocuSign for document signing.

## Pipeline stages (column-tracked with completion dates)
Active stages (phases 1-3):
  1. Added to Tracker      — set automatically when a new hire is added
  2. Sent Offer Letter     — set when the DocuSign envelope is sent
  3. Offer Letter Signed   — set when DocuSign status becomes "completed"

Future stages (not yet active): Background Submission, Background Cleared,
Added to ADP, Complete in ADP, Clear to Start, Prorations Sent.

## Webhook trigger (trigger_source=pa_webhook)
Run the full pipeline in order:
  1. Call find_employee_in_tracker — skip add if already exists
  2. Call add_employee_to_tracker — marks "Added to Tracker" automatically
  3. Call check_docusign_draft_exists — skip create if draft already exists
  4. Call create_docusign_envelope_draft
  5. Call send_docusign_envelope to send it immediately
  6. Call update_tracker_stage with stage="Sent Offer Letter"
  7. Send a {_INTERFACE} notification summarising what was done

## HR query trigger (trigger_source=teams_query)
Answer accurately using available tools. For status queries use get_onboarding_status.
After any DocuSign send action, always call update_tracker_stage to keep the tracker current.
When DocuSign status is "completed", call update_tracker_stage with stage="Offer Letter Signed".

Always be concise. If a tool fails, explain the error and suggest next steps.
Never expose raw credentials or envelope IDs unless directly asked.
"""


def _build_llm(tools: list) -> Any:
    if settings.is_gemini():
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
        ).bind_tools(tools)

    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
        max_tokens=4096,
    ).bind_tools(tools)


async def agent_node(state: OnboardingState, tools: list) -> dict[str, Any]:
    """Invoke the LLM with current messages and bound tools."""
    llm = _build_llm(tools)

    messages = list(state["messages"])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=_SYSTEM_PROMPT)] + messages

    response: AIMessage = await llm.ainvoke(messages)
    logger.debug("agent_node response: %s tool_calls", len(response.tool_calls))

    return {
        "messages": [response],
        "current_step": "tool_execution" if response.tool_calls else "completion",
    }


async def tool_executor_node(state: OnboardingState, tool_map: dict[str, Any]) -> dict[str, Any]:
    """Execute all tool calls from the last AIMessage in parallel."""
    last_message: AIMessage = state["messages"][-1]  # type: ignore[assignment]

    async def _run_tool(tool_call: dict[str, Any]) -> ToolMessage:
        name = tool_call["name"]
        args = tool_call["args"]
        call_id = tool_call["id"]

        if name not in tool_map:
            return ToolMessage(
                content=f"Unknown tool: {name}",
                tool_call_id=call_id,
                name=name,
            )
        try:
            tool = tool_map[name]
            result = await tool.arun(args) if asyncio.iscoroutinefunction(tool.arun) else tool.run(args)
            return ToolMessage(content=str(result), tool_call_id=call_id, name=name)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return ToolMessage(content=f"Error: {exc}", tool_call_id=call_id, name=name)

    tool_messages = await asyncio.gather(*[_run_tool(tc) for tc in last_message.tool_calls])

    return {
        "messages": list(tool_messages),
        "current_step": "agent",
    }


async def error_handler_node(state: OnboardingState) -> dict[str, Any]:
    """Increment retry counter; on final failure record the error."""
    retry_count = state.get("retry_count", 0) + 1
    error = state.get("error_message", "Unknown error")
    logger.warning("Error handler: retry %d — %s", retry_count, error)

    updates: dict[str, Any] = {"retry_count": retry_count, "current_step": "agent"}

    if retry_count >= 3:
        updates["current_step"] = "end"
        updates["completed"] = False
        # Append a summary message so the caller knows what happened
        updates["messages"] = [
            HumanMessage(
                content=f"[SYSTEM] Onboarding failed after {retry_count} retries. Last error: {error}"
            )
        ]

    return updates


async def completion_node(state: OnboardingState) -> dict[str, Any]:
    """Mark the run as completed."""
    logger.info("Onboarding completed for %s", state.get("employee_email", "unknown"))
    return {
        "completed": True,
        "current_step": "end",
        "excel_status": "Completed",
    }


# ---------------------------------------------------------------------------
# Routing helpers (used as conditional edges in graph.py)
# ---------------------------------------------------------------------------


def should_continue(state: OnboardingState) -> str:
    """Decide the next node after agent_node."""
    last = state["messages"][-1] if state["messages"] else None

    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_executor"

    step = state.get("current_step", "")
    if step == "end":
        return "end"

    error = state.get("error_message", "")
    if error:
        return "error_handler"

    return "completion"


def after_error_handler(state: OnboardingState) -> str:
    """Route after error_handler: retry or give up."""
    if state.get("retry_count", 0) >= 3:
        return "end"
    return "agent"
