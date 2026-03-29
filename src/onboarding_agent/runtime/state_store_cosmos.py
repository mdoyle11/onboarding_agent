"""Cosmos DB state store implementation."""

from __future__ import annotations

import logging
from typing import Any

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

logger = logging.getLogger(__name__)


class CosmosStateStore:
    """Azure Cosmos DB-backed state store with /namespace partition key."""

    def __init__(
        self,
        endpoint: str,
        key: str,
        database_name: str = "onboarding-agent",
        container_name: str = "state-records",
    ) -> None:
        client = CosmosClient(endpoint, credential=key)
        database = client.get_database_client(database_name)
        self._container = database.get_container_client(container_name)
        logger.info(
            "Cosmos state store ready: %s/%s",
            database_name,
            container_name,
        )

    def _doc_id(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        try:
            item = self._container.read_item(
                item=self._doc_id(namespace, key),
                partition_key=namespace,
            )
            return item.get("payload") or item.get("value")
        except CosmosResourceNotFoundError:
            return None

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        self._container.upsert_item({
            "id": self._doc_id(namespace, key),
            "namespace": namespace,
            "key": key,
            "payload": value,
        })

    async def delete(self, namespace: str, key: str) -> None:
        try:
            self._container.delete_item(
                item=self._doc_id(namespace, key),
                partition_key=namespace,
            )
        except CosmosResourceNotFoundError:
            pass

    async def list_keys(self, namespace: str) -> list[str]:
        query = "SELECT c.key FROM c WHERE c.namespace = @ns"
        params = [{"name": "@ns", "value": namespace}]
        items = self._container.query_items(
            query=query,
            parameters=params,
            partition_key=namespace,
        )
        return [item["key"] for item in items]

    async def get_all(self, namespace: str) -> dict[str, dict[str, Any]]:
        query = 'SELECT c.key, c.payload, c["value"] AS legacy_value FROM c WHERE c.namespace = @ns'
        params = [{"name": "@ns", "value": namespace}]
        items = self._container.query_items(
            query=query,
            parameters=params,
            partition_key=namespace,
        )
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            payload = item.get("payload") or item.get("legacy_value")
            if isinstance(payload, dict):
                result[item["key"]] = payload
        return result
