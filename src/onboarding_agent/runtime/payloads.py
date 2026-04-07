"""Shared payload extraction helpers for webhook and job inputs."""

from __future__ import annotations

from typing import Any


def payload_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def payload_any(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            value = payload.get(key)
            if value not in (None, ""):
                return value
    return ""
