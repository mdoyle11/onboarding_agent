#!/usr/bin/env python3
"""Delete persisted runtime state records from the Cosmos-backed state store.

Examples:
  python scripts/reset_runtime_state.py \
    --cosmos-endpoint https://example.documents.azure.com:443/ \
    --cosmos-key '...' \
    --database onboarding-agent \
    --container state-records \
    --employee-email mdoyle@example.com \
    --all-conversation-refs
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError


NS_NEW_HIRE = "new_hire_card"
NS_DOCUSIGN = "docusign_card"
NS_CONVERSATION_REF = "conversation_ref"


def _delete_item(container: Any, namespace: str, key: str) -> bool:
    doc_id = f"{namespace}:{key}"
    try:
        container.delete_item(item=doc_id, partition_key=namespace)
        print(f"deleted {doc_id}")
        return True
    except CosmosResourceNotFoundError:
        print(f"not found {doc_id}")
        return False


def _load_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    if isinstance(payload, dict):
        return payload
    legacy = item.get("value")
    if isinstance(legacy, dict):
        return legacy
    return {}


def _delete_conversation_refs(container: Any, channel_id: str | None, delete_all: bool) -> int:
    query = 'SELECT c.id, c.key, c.payload, c["value"] AS legacy_value FROM c WHERE c.namespace = @ns'
    params = [{"name": "@ns", "value": NS_CONVERSATION_REF}]
    items = list(container.query_items(query=query, parameters=params, partition_key=NS_CONVERSATION_REF))
    deleted = 0

    for item in items:
        key = str(item.get("key", ""))
        payload = _load_payload(item)
        conversation = payload.get("conversation", {}) if isinstance(payload, dict) else {}
        conversation_id = str(conversation.get("id", ""))
        conversation_name = str(conversation.get("name", ""))

        should_delete = delete_all
        if channel_id and not should_delete:
            should_delete = (
                channel_id == key
                or channel_id == conversation_id
                or channel_id == conversation_name
                or channel_id in key
                or channel_id in conversation_id
            )

        if should_delete:
            container.delete_item(item=item["id"], partition_key=NS_CONVERSATION_REF)
            print(f"deleted {item['id']}")
            deleted += 1

    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cosmos-endpoint", default=os.getenv("COSMOS_ENDPOINT", ""))
    parser.add_argument("--cosmos-key", default=os.getenv("COSMOS_KEY", ""))
    parser.add_argument("--database", default=os.getenv("COSMOS_DATABASE_NAME", "onboarding-agent"))
    parser.add_argument("--container", default=os.getenv("COSMOS_CONTAINER_NAME", "state-records"))
    parser.add_argument("--employee-email", default="")
    parser.add_argument("--channel-id", default="")
    parser.add_argument("--all-conversation-refs", action="store_true")
    args = parser.parse_args()

    if not args.cosmos_endpoint or not args.cosmos_key:
        raise SystemExit("COSMOS endpoint/key are required via args or env")

    client = CosmosClient(args.cosmos_endpoint, credential=args.cosmos_key)
    container = client.get_database_client(args.database).get_container_client(args.container)

    deleted = 0
    if args.employee_email:
        email_key = args.employee_email.strip().lower()
        deleted += int(_delete_item(container, NS_NEW_HIRE, email_key))
        deleted += int(_delete_item(container, NS_DOCUSIGN, email_key))

    if args.channel_id or args.all_conversation_refs:
        deleted += _delete_conversation_refs(
            container,
            channel_id=args.channel_id.strip() or None,
            delete_all=args.all_conversation_refs,
        )

    print(json.dumps({"deleted": deleted}, indent=2))


if __name__ == "__main__":
    main()
