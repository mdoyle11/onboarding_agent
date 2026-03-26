"""Tests for OnboardingState schema and defaults."""

from onboarding_agent.agent.state import OnboardingState, default_state


def test_default_state_has_all_keys():
    state = default_state()
    # Verify every key defined in the TypedDict is present
    annotations = OnboardingState.__annotations__
    for key in annotations:
        assert key in state, f"Missing key: {key}"


def test_default_state_values():
    state = default_state()
    assert state["retry_count"] == 0
    assert state["completed"] is False
    assert state["docusign_draft_exists"] is False
    assert state["teams_notification_sent"] is False
    assert state["messages"] == []
    assert state["forms_data_raw"] == {}


def test_default_state_strings_empty():
    state = default_state()
    string_fields = [
        "trigger_source", "triggered_by_user_id", "employee_email", "employee_name",
        "employee_start_date", "employee_department", "employee_location", "employee_manager_email",
        "forms_submission_id", "excel_row_id", "excel_status",
        "docusign_envelope_id", "docusign_envelope_status",
        "teams_channel_id", "current_step", "error_message",
    ]
    for field in string_fields:
        assert state[field] == "", f"Expected empty string for {field}, got {state[field]!r}"
