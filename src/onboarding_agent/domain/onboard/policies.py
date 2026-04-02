"""Status-change workflow definitions for onboarding operations."""

from __future__ import annotations

WORKFLOW_NEW_HIRE = "new_hire"
WORKFLOW_PROMOTION = "promotion"
WORKFLOW_PAY_INCREASE = "pay_increase"
WORKFLOW_TRANSFER_IN = "transfer_in"
WORKFLOW_REHIRE = "rehire"
WORKFLOW_OTHER = "other"

_WORKFLOW_ALIASES = {
    "new hire": WORKFLOW_NEW_HIRE,
    "promotion": WORKFLOW_PROMOTION,
    "pay increase": WORKFLOW_PAY_INCREASE,
    "transfer in": WORKFLOW_TRANSFER_IN,
    "rehire": WORKFLOW_REHIRE,
}

_WORKFLOW_EXCLUDED_STAGES: dict[str, tuple[str, ...]] = {
    WORKFLOW_PROMOTION: (
        "Background Submission",
        "Background Cleared",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
    WORKFLOW_PAY_INCREASE: (
        "Added to Staff Roster",
        "Background Submission",
        "Background Cleared",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
    WORKFLOW_TRANSFER_IN: (
        "Background Submission",
        "Background Cleared",
        "Employee Complete ADP Profile",
    ),
    WORKFLOW_REHIRE: (
        "Employee Complete ADP Profile",
    ),
}


def normalize_workflow_type(raw_status_change: str) -> str:
    """Resolve a workflow type from a status-change label."""
    normalized = raw_status_change.strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    if not normalized:
        return WORKFLOW_NEW_HIRE
    return _WORKFLOW_ALIASES.get(normalized, WORKFLOW_OTHER)


def excluded_stages_for(workflow_type: str) -> tuple[str, ...]:
    """Return stages that should be marked N/A for the workflow."""
    return _WORKFLOW_EXCLUDED_STAGES.get(workflow_type, ())
