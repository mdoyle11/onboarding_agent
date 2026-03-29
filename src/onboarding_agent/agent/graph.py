"""StateGraph wiring — compiles the onboarding agent graph at import time."""

import logging
import os
from functools import partial
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph

from onboarding_agent.agent.nodes import (
    after_error_handler,
    agent_node,
    completion_node,
    error_handler_node,
    should_continue,
    tool_executor_node,
)
from onboarding_agent.runtime.checkpointing import create_checkpointer
from onboarding_agent.agent.state import OnboardingState

logger = logging.getLogger(__name__)

# MCP server command — started as a subprocess via stdio transport
_MCP_SERVER_CMD = ["python", "-m", "onboarding_agent.mcp_server.server"]


async def build_graph() -> Any:
    """
    Load MCP tools via stdio transport, wire the StateGraph, and return the
    compiled graph.  Call once at application startup and cache the result.
    """
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

    tools: list[BaseTool] = await client.get_tools()
    tool_map: dict[str, BaseTool] = {t.name: t for t in tools}
    logger.info("Loaded %d MCP tools: %s", len(tools), list(tool_map))

    # -----------------------------------------------------------------------
    # Graph wiring
    # -----------------------------------------------------------------------
    builder = StateGraph(OnboardingState)

    builder.add_node("agent", partial(agent_node, tools=tools))
    builder.add_node("tool_executor", partial(tool_executor_node, tool_map=tool_map))
    builder.add_node("error_handler", error_handler_node)
    builder.add_node("completion", completion_node)

    builder.add_edge(START, "agent")

    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tool_executor": "tool_executor",
            "error_handler": "error_handler",
            "completion": "completion",
            "end": END,
        },
    )

    builder.add_edge("tool_executor", "agent")

    builder.add_conditional_edges(
        "error_handler",
        after_error_handler,
        {"agent": "agent", "end": END},
    )

    builder.add_edge("completion", END)

    compiled = builder.compile(checkpointer=await create_checkpointer())
    logger.info("Graph compiled successfully")
    return compiled


# Module-level cache — populated by server.py at startup
compiled_graph: Any = None
