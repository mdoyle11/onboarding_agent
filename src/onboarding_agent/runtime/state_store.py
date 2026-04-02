"""Pluggable state store abstraction for durable key-value persistence."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

TTL_SECONDS_FIELD = "__ttl_seconds"


class StateStore(ABC):
    """Abstract key-value store partitioned by namespace."""

    @abstractmethod
    async def get(self, namespace: str, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete(self, namespace: str, key: str) -> None: ...

    @abstractmethod
    async def list_keys(self, namespace: str) -> list[str]: ...

    @abstractmethod
    async def get_all(self, namespace: str) -> dict[str, dict[str, Any]]: ...


class FileStateStore(StateStore):
    """File-backed state store — one JSON file per namespace."""

    def __init__(self, directory: str = "data") -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str) -> Path:
        return self._dir / f"{namespace}.json"

    def _load(self, namespace: str) -> dict[str, dict[str, Any]]:
        path = self._path(namespace)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    return cast(dict[str, dict[str, Any]], data)
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not read %s, starting fresh", path)
        return {}

    def _save(self, namespace: str, data: dict[str, dict[str, Any]]) -> None:
        self._path(namespace).write_text(json.dumps(data, indent=2))

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self._load(namespace).get(key)

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        data = self._load(namespace)
        data[key] = {
            item_key: item_value
            for item_key, item_value in value.items()
            if item_key != TTL_SECONDS_FIELD
        }
        self._save(namespace, data)

    async def delete(self, namespace: str, key: str) -> None:
        data = self._load(namespace)
        data.pop(key, None)
        self._save(namespace, data)

    async def list_keys(self, namespace: str) -> list[str]:
        return list(self._load(namespace).keys())

    async def get_all(self, namespace: str) -> dict[str, dict[str, Any]]:
        return self._load(namespace)


# Module-level singleton — set during startup
store: StateStore | None = None
session_store: StateStore | None = None


def create_state_store(backend: str, **kwargs: Any) -> StateStore:
    """Factory that returns the configured StateStore implementation."""
    if backend == "cosmos":
        from onboarding_agent.runtime.state_store_cosmos import CosmosStateStore

        return CosmosStateStore(
            endpoint=kwargs["cosmos_endpoint"],
            key=kwargs["cosmos_key"],
            database_name=kwargs.get("cosmos_database_name", "onboarding-agent"),
            container_name=kwargs.get("cosmos_container_name", "state-records"),
        )
    return FileStateStore(directory=kwargs.get("state_store_dir", "data"))
