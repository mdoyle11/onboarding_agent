"""Tests for staff roster helpers and Teams card actions."""

from onboarding_agent.integrations.adaptive_cards import docusign_status_card
from onboarding_agent.integrations.graph_client import _column_letter, _header_map
from onboarding_agent.integrations.teams_bot import _card_action_to_command


def test_column_letter_supports_multi_letter_ranges():
    assert _column_letter(0) == "A"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"


def test_header_map_matches_normalized_staff_roster_headers():
    header = ["Employee Name", "Employee Email", "Group", "Start Date"]
    aliases = {
        "name": {"employee name"},
        "email": {"employee email"},
        "group": {"job category", "group"},
        "start_date": {"start date"},
    }
    assert _header_map(header, aliases) == {
        "name": 0,
        "email": 1,
        "group": 2,
        "start_date": 3,
    }


def test_completed_docusign_card_includes_staff_roster_action():
    card = docusign_status_card(
        employee_email="alice@example.com",
        envelope_id="env-123",
        status="completed",
        summary="Signed.",
    )

    assert any(action.get("title") == "Add To Staff Roster" for action in card["actions"])
    assert any(block.get("id") == "job_category" for block in card["body"])


def test_card_action_to_command_uses_exact_job_category():
    command = _card_action_to_command(
        {
            "action": "add_to_staff_roster",
            "employee_email": "alice@example.com",
            "job_category": "Teacher",
        }
    )
    assert command == "add alice@example.com to the staff roster using the exact job category Teacher"
