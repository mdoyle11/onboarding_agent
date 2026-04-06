"""Tests for workflow taxonomy and policy separation."""

from onboarding_agent.domain.offboard.policies import is_offboarding_workflow
from onboarding_agent.domain.onboard.policies import (
    allows_offer_letter_action,
    is_onboarding_workflow,
    uses_second_position_roster_action,
)
from onboarding_agent.domain.temp.policies import (
    is_temporary_workflow,
    leave_status_for_workflow,
)
from onboarding_agent.domain.workflows import normalize_workflow_type


def test_normalize_workflow_type_routes_domains_by_status_change() -> None:
    assert normalize_workflow_type("Second Position") == "second_position"
    assert normalize_workflow_type("Transfer Out") == "transfer_out"
    assert normalize_workflow_type("Leave Start") == "leave_start"


def test_workflow_family_classifiers_are_domain_aligned() -> None:
    assert is_onboarding_workflow("second_position") is True
    assert is_offboarding_workflow("second_position") is False
    assert is_temporary_workflow("second_position") is False

    assert is_offboarding_workflow("transfer_out") is True
    assert is_temporary_workflow("leave_end") is True


def test_second_position_policy_uses_roster_action_without_offer_letter() -> None:
    assert uses_second_position_roster_action("second_position") is True
    assert allows_offer_letter_action("second_position") is False


def test_leave_workflow_policy_maps_to_expected_roster_status() -> None:
    assert leave_status_for_workflow("leave_start") == ("On Leave", "Leave started")
    assert leave_status_for_workflow("leave_end") == ("Active", "Leave ended")
