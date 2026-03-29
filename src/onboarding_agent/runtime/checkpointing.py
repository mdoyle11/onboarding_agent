"""Checkpointer factory for LangGraph persistence."""

from __future__ import annotations

from contextlib import AsyncExitStack
import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)
_cosmos_checkpointer_stack: AsyncExitStack | None = None


async def create_checkpointer() -> Any:
    """Return the configured LangGraph checkpointer."""
    global _cosmos_checkpointer_stack

    backend = settings.graph_checkpoint_backend.strip().lower()
    if backend == "memory":
        logger.info("Using in-memory LangGraph checkpointer")
        return MemorySaver()

    if backend != "cosmos":
        raise ValueError(f"Unsupported graph checkpoint backend: {settings.graph_checkpoint_backend}")

    try:
        from langgraph_checkpoint_cosmos.aio import AsyncCosmosDBSaver
    except ImportError as exc:
        raise RuntimeError(
            "GRAPH_CHECKPOINT_BACKEND=cosmos requires the "
            "'langgraph-checkpoint-cosmos' package to be installed"
        ) from exc

    logger.info(
        "Using Cosmos LangGraph checkpointer (%s/%s)",
        settings.graph_checkpoint_cosmos_database_name,
        settings.graph_checkpoint_cosmos_container_name,
    )

    if _cosmos_checkpointer_stack is not None:
        await _cosmos_checkpointer_stack.aclose()

    stack = AsyncExitStack()
    saver = await stack.enter_async_context(
        AsyncCosmosDBSaver.from_conn_info(
            endpoint=settings.cosmos_endpoint,
            credential=settings.cosmos_key,
            database_name=settings.graph_checkpoint_cosmos_database_name,
            container_name=settings.graph_checkpoint_cosmos_container_name,
        )
    )
    _cosmos_checkpointer_stack = stack
    return saver


async def close_checkpointer() -> None:
    """Close any managed resources held by the configured checkpointer."""
    global _cosmos_checkpointer_stack

    if _cosmos_checkpointer_stack is None:
        return

    await _cosmos_checkpointer_stack.aclose()
    _cosmos_checkpointer_stack = None
