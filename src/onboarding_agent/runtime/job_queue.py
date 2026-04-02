"""Minimal job queue abstraction for durable webhook handoff."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueueJob:
    """Serialized unit of work consumed by the background worker."""

    job_type: str
    payload: dict[str, Any]


JobHandler = Callable[[QueueJob], Awaitable[None]]


class JobQueue(Protocol):
    async def start(self) -> None: ...

    async def enqueue(self, job_type: str, payload: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


class LocalJobQueue:
    """Development queue that executes jobs in-process."""

    def __init__(self, handler: JobHandler) -> None:
        self._handler = handler
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        logger.info("Local job queue ready")

    async def enqueue(self, job_type: str, payload: dict[str, Any]) -> None:
        job = QueueJob(job_type=job_type, payload=payload)
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        if not self._tasks:
            return
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, job: QueueJob) -> None:
        try:
            await self._handler(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Local job queue handler failed for %s", job.job_type)


class AzureStorageJobQueue:
    """Azure Storage Queue-backed job queue with a single in-process worker."""

    def __init__(
        self,
        handler: JobHandler,
        *,
        connection_string: str,
        queue_name: str,
        poll_interval_seconds: float = 1.0,
        visibility_timeout_seconds: int = 300,
        max_dequeue_count: int = 5,
    ) -> None:
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.queue import QueueClient

        self._handler = handler
        self._client = QueueClient.from_connection_string(connection_string, queue_name)
        self._resource_exists_error = ResourceExistsError
        self._poll_interval_seconds = poll_interval_seconds
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._max_dequeue_count = max_dequeue_count
        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            await asyncio.to_thread(self._client.create_queue)
        except self._resource_exists_error:
            logger.info("Azure Storage Queue already exists; reusing %s", self._client.queue_name)
        self._worker_task = asyncio.create_task(self._run_worker())
        logger.info("Azure Storage Queue worker started")

    async def enqueue(self, job_type: str, payload: dict[str, Any]) -> None:
        body = json.dumps({"job_type": job_type, "payload": payload})
        await asyncio.to_thread(self._client.send_message, body)

    async def close(self) -> None:
        self._stop_event.set()
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None

    async def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            message = await self._receive_message()
            if message is None:
                await self._sleep_until_next_poll()
                continue
            await self._handle_message(message)

    async def _receive_message(self) -> Any | None:
        def _receive() -> Any | None:
            messages = list(
                self._client.receive_messages(
                    messages_per_page=1,
                    visibility_timeout=self._visibility_timeout_seconds,
                )
            )
            return messages[0] if messages else None

        return await asyncio.to_thread(_receive)

    async def _handle_message(self, message: Any) -> None:
        dequeue_count = int(getattr(message, "dequeue_count", 0) or 0)
        if dequeue_count > self._max_dequeue_count:
            logger.error(
                "Deleting poison queue message %s after dequeue_count=%s",
                getattr(message, "id", "?"),
                dequeue_count,
            )
            await asyncio.to_thread(self._client.delete_message, message.id, message.pop_receipt)
            return

        try:
            raw = json.loads(message.content)
            job = QueueJob(
                job_type=str(raw["job_type"]),
                payload=dict(raw["payload"]),
            )
        except Exception:
            logger.exception("Dropping malformed queue message %s", getattr(message, "id", "?"))
            await asyncio.to_thread(self._client.delete_message, message.id, message.pop_receipt)
            return

        try:
            await self._handler(job)
        except Exception:
            logger.exception(
                "Queue handler failed for %s (message=%s dequeue_count=%s)",
                job.job_type,
                getattr(message, "id", "?"),
                getattr(message, "dequeue_count", "?"),
            )
            return

        await asyncio.to_thread(self._client.delete_message, message.id, message.pop_receipt)

    async def _sleep_until_next_poll(self) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
        except TimeoutError:
            return


def create_job_queue(
    backend: str,
    handler: JobHandler,
    **kwargs: Any,
) -> JobQueue:
    """Factory that returns the configured JobQueue implementation."""
    normalized = backend.strip().lower()
    if normalized == "azure":
        connection_string = str(kwargs.get("azure_storage_queue_connection_string", "")).strip()
        if not connection_string:
            raise ValueError("Azure job queue backend requires AZURE_STORAGE_QUEUE_CONNECTION_STRING")
        return AzureStorageJobQueue(
            handler,
            connection_string=connection_string,
            queue_name=str(kwargs.get("azure_storage_queue_name", "onboarding-jobs")),
            poll_interval_seconds=float(kwargs.get("queue_poll_interval_seconds", 1.0)),
            max_dequeue_count=int(kwargs.get("queue_max_dequeue_count", 5)),
        )
    return LocalJobQueue(handler)
