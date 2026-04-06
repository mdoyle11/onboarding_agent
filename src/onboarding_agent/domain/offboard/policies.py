"""Offboarding workflow definitions and helpers."""

from __future__ import annotations

from onboarding_agent.domain.workflows import (
    WORKFLOW_SEPARATION,
    WORKFLOW_TRANSFER_OUT,
)

OFFBOARD_WORKFLOWS = frozenset({
    WORKFLOW_SEPARATION,
    WORKFLOW_TRANSFER_OUT,
})

_OFFBOARD_EXCLUDED_STAGES: dict[str, tuple[str, ...]] = {
    WORKFLOW_SEPARATION: (
        "Sent Offer Letter",
        "Offer Letter Signed",
        "Background Submission",
        "Background Cleared",
        "Added to ADP",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
    WORKFLOW_TRANSFER_OUT: (
        "Sent Offer Letter",
        "Offer Letter Signed",
        "Background Submission",
        "Background Cleared",
        "Employee Complete ADP Profile",
        "Clear to Start",
        "Drug Screening",
    ),
}

_SEPARATIONS_SHEET_WORKFLOWS = frozenset({
    WORKFLOW_SEPARATION,
    WORKFLOW_TRANSFER_OUT,
})


def is_offboarding_workflow(workflow_type: str) -> bool:
    """True for workflows that remove an employee from an active placement."""
    return workflow_type in OFFBOARD_WORKFLOWS


def offboarding_excluded_stages_for(workflow_type: str) -> tuple[str, ...]:
    """Return stages that should be marked N/A for offboarding workflows."""
    return _OFFBOARD_EXCLUDED_STAGES.get(workflow_type, ())


def uses_separations_sheet(workflow_type: str) -> bool:
    """True when the workflow appends to the Separations workbook."""
    return workflow_type in _SEPARATIONS_SHEET_WORKFLOWS
