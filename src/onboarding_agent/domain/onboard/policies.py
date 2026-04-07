"""Onboarding workflow definitions and helpers."""

from __future__ import annotations

from onboarding_agent.domain.workflows import (
    WORKFLOW_NEW_HIRE,
    WORKFLOW_OTHER,
    WORKFLOW_PAY_INCREASE,
    WORKFLOW_PROMOTION,
    WORKFLOW_REHIRE,
    WORKFLOW_SECOND_POSITION,
    WORKFLOW_TRANSFER_IN,
)

ONBOARDING_WORKFLOWS = frozenset({
    WORKFLOW_NEW_HIRE,
    WORKFLOW_PROMOTION,
    WORKFLOW_PAY_INCREASE,
    WORKFLOW_TRANSFER_IN,
    WORKFLOW_REHIRE,
    WORKFLOW_SECOND_POSITION,
    WORKFLOW_OTHER,
})

_ONBOARDING_EXCLUDED_STAGES: dict[str, tuple[str, ...]] = {
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
}


def is_onboarding_workflow(workflow_type: str) -> bool:
    """True for onboarding-family workflows, including second position."""
    return workflow_type in ONBOARDING_WORKFLOWS


def onboarding_excluded_stages_for(workflow_type: str) -> tuple[str, ...]:
    """Return stages that should be marked N/A for onboarding workflows."""
    return _ONBOARDING_EXCLUDED_STAGES.get(workflow_type, ())


def allows_email_action(workflow_type: str) -> bool:
    """True when the workflow should expose the welcome-email action."""
    return workflow_type in {WORKFLOW_NEW_HIRE, WORKFLOW_REHIRE}


def allows_offer_letter_action(workflow_type: str) -> bool:
    """True when the workflow should expose the offer-letter draft action."""
    return workflow_type != WORKFLOW_SECOND_POSITION


def uses_second_position_roster_action(workflow_type: str) -> bool:
    """True when the workflow should drive a second-position roster add."""
    return workflow_type == WORKFLOW_SECOND_POSITION
