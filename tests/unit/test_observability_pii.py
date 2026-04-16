"""Tests for telemetry redaction helpers."""

from onboarding_agent.observability.pii import (
    email_domain,
    hash_identifier,
    identifier_attributes,
    redact_text,
    safe_attributes,
)


def test_hash_identifier_is_stable_and_does_not_expose_raw_value() -> None:
    first = hash_identifier("Employee@Example.com", salt="salt")
    second = hash_identifier("employee@example.com", salt="salt")

    assert first == second
    assert len(first) == 16
    assert "employee" not in first


def test_redact_text_replaces_email_guid_and_long_numbers() -> None:
    result = redact_text(
        "Move employee@example.com for 11111111-2222-3333-4444-555555555555 submission 123456789.",
        salt="salt",
    )

    assert "employee@example.com" not in result
    assert "<EMAIL:" in result
    assert "11111111-2222-3333-4444-555555555555" not in result
    assert "123456789" not in result
    assert "<ID>" in result
    assert "<NUMBER>" in result


def test_safe_attributes_redacts_sensitive_keys_and_nested_values() -> None:
    result = safe_attributes(
        {
            "employee_email": "employee@example.com",
            "api_key": "secret",
            "employee_name": "Nancy Cruz",
            "payload": {"personal_email": "person@example.com", "staff_name": "Alice Smith"},
            "onboarding.tool_name": "get_onboarding_status",
        },
        salt="salt",
    )

    assert "employee@example.com" not in str(result)
    assert "person@example.com" not in str(result)
    assert "Nancy Cruz" not in str(result)
    assert "Alice Smith" not in str(result)
    assert result["api_key"] == "<REDACTED>"
    assert result["employee_name"] == "<NAME>"
    assert result["onboarding.tool_name"] == "get_onboarding_status"
    assert "<EMAIL:" in str(result["payload"])
    assert "<NAME>" in str(result["payload"])


def test_redact_text_redacts_json_like_name_fields() -> None:
    result = redact_text(
        "{'employee_name': 'Nancy Cruz', \"manager_name\": \"Alice Smith\", 'tool_name': 'get_onboarding_status'}"
    )

    assert "Nancy Cruz" not in result
    assert "Alice Smith" not in result
    assert "'employee_name': '<NAME>'" in result
    assert '"manager_name": "<NAME>"' in result
    assert "get_onboarding_status" in result


def test_identifier_attributes_hashes_ids_but_preserves_email_domain() -> None:
    result = identifier_attributes(
        employee_email="employee@example.com",
        submission_id="143",
        teams_conversation_id="conversation",
        teams_user_id="user",
        salt="salt",
    )

    assert result["employee.email_domain"] == "example.com"
    assert result["employee.email_hash"] == hash_identifier("employee@example.com", salt="salt")
    assert result["submission.id_hash"] == hash_identifier("143", salt="salt")
    assert result["teams.conversation_hash"] == hash_identifier("conversation", salt="salt")
    assert result["teams.user_hash"] == hash_identifier("user", salt="salt")


def test_email_domain_returns_empty_for_non_email() -> None:
    assert email_domain("not-email") == ""
