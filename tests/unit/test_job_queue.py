"""Tests for the minimal job queue implementations."""

import asyncio
from types import SimpleNamespace

import pytest

from onboarding_agent.runtime.job_queue import AzureStorageJobQueue, LocalJobQueue


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


@pytest.mark.asyncio
async def test_azure_job_queue_deletes_poison_message_without_handling() -> None:
    handled = False

    async def handler(_job) -> None:
        nonlocal handled
        handled = True

    deleted: list[tuple[str, str]] = []

    class FakeClient:
        def delete_message(self, message_id: str, pop_receipt: str) -> None:
            deleted.append((message_id, pop_receipt))

    queue = object.__new__(AzureStorageJobQueue)
    queue._handler = handler
    queue._client = FakeClient()
    queue._max_dequeue_count = 5

    message = SimpleNamespace(
        id="msg-1",
        pop_receipt="receipt-1",
        dequeue_count=6,
        content='{"job_type":"background_clearance_webhook","payload":{"employeeEmail":"test"}}',
    )

    await queue._handle_message(message)

    assert handled is False
    assert deleted == [("msg-1", "receipt-1")]
