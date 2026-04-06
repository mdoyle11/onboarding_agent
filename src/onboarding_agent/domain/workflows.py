"""Workflow constants and shared status-change normalization."""

from __future__ import annotations

WORKFLOW_NEW_HIRE = "new_hire"
WORKFLOW_PROMOTION = "promotion"
WORKFLOW_PAY_INCREASE = "pay_increase"
WORKFLOW_TRANSFER_IN = "transfer_in"
WORKFLOW_REHIRE = "rehire"
WORKFLOW_SEPARATION = "separation"
WORKFLOW_SECOND_POSITION = "second_position"
WORKFLOW_TRANSFER_OUT = "transfer_out"
WORKFLOW_LEAVE_START = "leave_start"
WORKFLOW_LEAVE_END = "leave_end"
WORKFLOW_OTHER = "other"

_WORKFLOW_ALIASES = {
    "new hire": WORKFLOW_NEW_HIRE,
    "promotion": WORKFLOW_PROMOTION,
    "pay increase": WORKFLOW_PAY_INCREASE,
    "transfer in": WORKFLOW_TRANSFER_IN,
    "rehire": WORKFLOW_REHIRE,
    "separation": WORKFLOW_SEPARATION,
    "second position": WORKFLOW_SECOND_POSITION,
    "transfer out": WORKFLOW_TRANSFER_OUT,
    "leave start": WORKFLOW_LEAVE_START,
    "leave end": WORKFLOW_LEAVE_END,
}


def normalize_workflow_type(raw_status_change: str) -> str:
    """Resolve a workflow type from a status-change label."""
    normalized = raw_status_change.strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    if not normalized:
        return WORKFLOW_NEW_HIRE
    return _WORKFLOW_ALIASES.get(normalized, WORKFLOW_OTHER)
