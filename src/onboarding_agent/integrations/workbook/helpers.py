"""Workbook-specific row and header helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from onboarding_agent.integrations.workbook.schema import ACTIVE_STAGES, STAGE_ALIASES, STAGE_NAMES


def today_iso() -> str:
    return date.today().isoformat()


def normalize_header(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def column_letter(index: int) -> str:
    result = ""
    current = index + 1
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def header_map(header_row: list[Any], aliases: dict[str, set[str]]) -> dict[str, int]:
    normalized = {normalize_header(value): idx for idx, value in enumerate(header_row)}
    resolved: dict[str, int] = {}
    for key, names in aliases.items():
        for name in names:
            idx = normalized.get(normalize_header(name))
            if idx is not None:
                resolved[key] = idx
                break
    return resolved


def cell(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def row_to_stages(row: list[Any], stage_indices: dict[str, int]) -> dict[str, str]:
    return {
        stage: str(row[col_idx]) if len(row) > col_idx and row[col_idx] is not None else ""
        for stage, col_idx in stage_indices.items()
    }


def latest_active_stage(stages: dict[str, str]) -> str:
    latest = ""
    for stage in ACTIVE_STAGES:
        if stages.get(stage):
            latest = stage
    return latest


def stage_column_map(header_row: list[Any]) -> dict[str, int]:
    normalized = {normalize_header(value): idx for idx, value in enumerate(header_row)}
    resolved: dict[str, int] = {}
    for stage in STAGE_NAMES:
        idx = normalized.get(normalize_header(stage))
        if idx is not None:
            resolved[stage] = idx
    return resolved


def resolve_stage_name(stage_name: str, stage_indices: dict[str, int]) -> str | None:
    direct = stage_name.strip()
    if direct in stage_indices:
        return direct
    alias = STAGE_ALIASES.get(direct, "")
    if alias and alias in stage_indices:
        return alias
    return None
