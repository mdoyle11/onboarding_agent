"""Temporary-status workflow definitions and helpers."""

from __future__ import annotations

from onboarding_agent.domain.workflows import (
    WORKFLOW_LEAVE_END,
    WORKFLOW_LEAVE_START,
)

TEMPORARY_WORKFLOWS = frozenset({
    WORKFLOW_LEAVE_START,
    WORKFLOW_LEAVE_END,
})

_TEMPORARY_EXCLUDED_STAGES: dict[str, tuple[str, ...]] = {
    WORKFLOW_LEAVE_START: (
        "Sent Offer Letter",
        "Offer Letter Signed",
        "Background Submission",
        "Background Cleared",
        "Added to ADP",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
    WORKFLOW_LEAVE_END: (
        "Sent Offer Letter",
        "Offer Letter Signed",
        "Background Submission",
        "Background Cleared",
        "Added to ADP",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
}


def is_temporary_workflow(workflow_type: str) -> bool:
    """True for temporary status changes such as leave start/end."""
    return workflow_type in TEMPORARY_WORKFLOWS


def temporary_excluded_stages_for(workflow_type: str) -> tuple[str, ...]:
    """Return stages that should be marked N/A for leave workflows."""
    return _TEMPORARY_EXCLUDED_STAGES.get(workflow_type, ())


def leave_status_for_workflow(workflow_type: str) -> tuple[str, str]:
    """Return roster status and note prefix for the leave workflow."""
    if workflow_type == WORKFLOW_LEAVE_START:
        return "On Leave", "Leave started"
    return "Active", "Leave ended"
