"""Resolve user-facing workbook field names to canonical tool parameters."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from onboarding_agent.integrations.workbook.helpers import normalize_header


def _display_name(key: str) -> str:
    return key.replace("_", " ")


def _candidate_names(key: str, aliases: set[str]) -> set[str]:
    return {key, _display_name(key), *aliases}


def resolve_field_name(
    requested: str,
    aliases_by_key: dict[str, set[str]],
    *,
    blocked_aliases_by_key: dict[str, set[str]] | None = None,
    threshold: float = 0.72,
) -> dict[str, Any]:
    """Resolve a human field label to one canonical key.

    Returns a small structured result instead of raising so MCP tools can ask
    users for clarification without attempting a write.
    """
    requested_text = str(requested or "").strip()
    requested_normalized = normalize_header(requested_text)
    if not requested_normalized:
        return {"success": False, "needs_clarification": True, "error": "Column name is required."}

    exact_matches: list[str] = []
    scored: list[tuple[float, str, str]] = []
    for key, aliases in aliases_by_key.items():
        for name in _candidate_names(key, aliases):
            candidate_normalized = normalize_header(name)
            if not candidate_normalized:
                continue
            if candidate_normalized == requested_normalized:
                exact_matches.append(key)
            score = SequenceMatcher(None, requested_normalized, candidate_normalized).ratio()
            if requested_normalized in candidate_normalized or candidate_normalized in requested_normalized:
                score = max(score, 0.86)
            scored.append((score, key, name))

    unique_exact = sorted(set(exact_matches))
    if len(unique_exact) == 1:
        return {"success": True, "field": unique_exact[0]}
    if len(unique_exact) > 1:
        return {
            "success": False,
            "needs_clarification": True,
            "error": f"Column '{requested_text}' matched multiple fields.",
            "matches": unique_exact,
        }

    blocked_aliases_by_key = blocked_aliases_by_key or {}
    blocked_exact: dict[str, str] = {}
    for key, aliases in blocked_aliases_by_key.items():
        for name in _candidate_names(key, aliases):
            blocked_exact[normalize_header(name)] = key
    if requested_normalized in blocked_exact:
        return {
            "success": False,
            "blocked": True,
            "field": blocked_exact[requested_normalized],
            "error": f"'{requested_text}' is a tracker stage. Use /update-stage instead of /update-field.",
        }

    best_by_key: dict[str, tuple[float, str]] = {}
    for score, key, name in scored:
        current = best_by_key.get(key)
        if current is None or score > current[0]:
            best_by_key[key] = (score, name)

    ranked = sorted(((score, key, name) for key, (score, name) in best_by_key.items()), reverse=True)
    if not ranked or ranked[0][0] < threshold:
        return {
            "success": False,
            "needs_clarification": True,
            "error": f"Column '{requested_text}' did not match a supported field.",
            "supported_fields": sorted(aliases_by_key),
        }

    top_score = ranked[0][0]
    close_matches = [key for score, key, _ in ranked if top_score - score < 0.04]
    if len(close_matches) > 1:
        return {
            "success": False,
            "needs_clarification": True,
            "error": f"Column '{requested_text}' matched multiple fields.",
            "matches": close_matches,
        }

    return {"success": True, "field": ranked[0][1], "matched": ranked[0][2], "score": top_score}
