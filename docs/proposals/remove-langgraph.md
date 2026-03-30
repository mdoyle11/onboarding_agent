# Proposal: Remove LangGraph in Favour of a Plain Agent Loop

**Status:** Planned
**Branch:** `refactor/remove-langgraph`
**Created:** 2026-03-30

## Problem

LangGraph was introduced early in the project when the expectation was that a single graph invocation would orchestrate the entire onboarding workflow end-to-end. In practice, the workflow is human-in-the-loop at the business level — HR interacts with Excel trackers and Teams cards between steps — so the agent is invoked independently for each event (webhook, Teams message, card action). Each invocation runs for a few seconds, executes a tool loop, and exits.

This means:
- The graph topology is linear (no branching, no parallel nodes, no subgraphs, no `interrupt()`)
- `OnboardingState` carries ~20 fields but most are passed through unused across nodes
- Checkpointing stores conversational context that we've already capped to 5 messages and 10-turn sessions
- We built `teams_session.py`, `_trim_messages_for_invoke`, and checkpoint TTLs to work around LangGraph's unbounded state growth
- The real workflow state machine is the Excel tracker column progression, not the graph

The core agent loop is: call LLM → if tool calls, execute them, repeat → if no tool calls, done → retry up to 3 times on error. That's a `while` loop, not a state graph.

## Proposed Changes

### Remove
- `agent/graph.py` — StateGraph wiring
- `agent/state.py` — OnboardingState TypedDict
- `runtime/checkpointing.py` — AsyncCosmosDBSaver factory
- `langgraph-checkpoints` Cosmos container (Terraform resource + variable + output)
- LangGraph, `langgraph-checkpoint-cosmosdb`, and `langchain-core` dependencies (keep `langchain-anthropic` and `langchain-google-genai` for the chat model wrappers, or replace with direct SDK calls)

### Replace with
- A single `agent/runner.py` module containing an async `run_agent(messages, trigger_context, tools)` function that implements the tool loop directly
- Chat history stored in the existing Cosmos state store under a `"chat_history"` namespace, keyed the same way `teams_session.py` keys sessions today
- Session rotation logic stays but manages a plain message list instead of LangGraph thread IDs
- Retry logic becomes a try/except in the loop

### Simplify
- `agent/nodes.py` collapses into `agent/runner.py` — the system prompt, LLM construction, message trimming, and tool execution all live in one module
- `teams_session.py` no longer needs to produce LangGraph-compatible thread IDs — it just manages session keys for chat history lookup
- `conversation-sessions` Cosmos container may be removable if chat history records use the same TTL pattern

### Keep as-is
- MCP tool server (`mcp_server/`) — unchanged, tools are still loaded via `MultiServerMCPClient`
- All integrations (`teams_bot.py`, `graph_client.py`, `docusign_client.py`, etc.)
- External state stores (`state_store.py`, `state_store_cosmos.py`)
- Job queue and webhook handling
- Excel tracker as the source of truth for workflow state

## Sketch

```python
async def run_agent(
    messages: list[BaseMessage],
    tools: list[BaseTool],
    tool_map: dict[str, BaseTool],
    max_retries: int = 3,
) -> list[BaseMessage]:
    """Run the agent tool loop until the LLM stops calling tools."""
    llm = _build_llm(tools)

    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                return messages

            tool_results = await _execute_tools(response.tool_calls, tool_map)
            messages.extend(tool_results)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning("Agent attempt %d failed: %s", attempt + 1, exc)

    return messages
```

## Timing

This should be coordinated with the M365 Agents SDK migration (`project_m365_migration.md`) since both touch the bot layer. Doing them together avoids reworking `teams_bot.py` twice.

## Why not now

The current implementation works. This is a simplification refactor, not a bug fix. The best time to make this change is when we're already reworking the bot layer for the M365 Agents SDK migration.
