"""Tests for the minimal job queue implementations."""

import asyncio

import pytest

from onboarding_agent.runtime.job_queue import LocalJobQueue


@pytest.mark.asyncio
async def test_local_job_queue_executes_handler() -> None:
    seen: list[tuple[str, dict[str, str]]] = []
    handled = asyncio.Event()

    async def handler(job) -> None:
        seen.append((job.job_type, job.payload))
        handled.set()

    queue = LocalJobQueue(handler)
    await queue.start()
    await queue.enqueue("new_hire_webhook", {"employeeEmail": "alice@example.com"})

    await asyncio.wait_for(handled.wait(), timeout=1)
    assert seen == [("new_hire_webhook", {"employeeEmail": "alice@example.com"})]

    await queue.close()
