"""Status-change workflow definitions for onboarding operations."""

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

# Stages excluded (marked "N/A") for each workflow.
# Unlisted workflows (New Hire) have all stages active.
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
    WORKFLOW_SECOND_POSITION: (
        "Sent Offer Letter",
        "Offer Letter Signed",
        "Background Submission",
        "Background Cleared",
        "Employee Complete ADP Profile",
        "Proration",
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

_SEPARATION_WORKFLOWS = frozenset({
    WORKFLOW_SEPARATION,
    WORKFLOW_SECOND_POSITION,
    WORKFLOW_TRANSFER_OUT,
    WORKFLOW_LEAVE_START,
    WORKFLOW_LEAVE_END,
})

_SEPARATIONS_SHEET_WORKFLOWS = frozenset({
    WORKFLOW_SEPARATION,
    WORKFLOW_TRANSFER_OUT,
})

_LEAVE_WORKFLOWS = frozenset({
    WORKFLOW_LEAVE_START,
    WORKFLOW_LEAVE_END,
})


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


def is_separation_workflow(workflow_type: str) -> bool:
    """True for all separation-category workflows (not onboarding)."""
    return workflow_type in _SEPARATION_WORKFLOWS


def is_separations_sheet_workflow(workflow_type: str) -> bool:
    """True for workflows that move the employee to the Separations sheet."""
    return workflow_type in _SEPARATIONS_SHEET_WORKFLOWS


def is_leave_workflow(workflow_type: str) -> bool:
    """True for Leave Start / Leave End workflows."""
    return workflow_type in _LEAVE_WORKFLOWS
