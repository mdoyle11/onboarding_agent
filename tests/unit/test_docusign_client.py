"""Tests for DocuSign client identity-field matching behavior."""

from types import SimpleNamespace
from unittest.mock import patch

from onboarding_agent.integrations.docusign_client import DocuSignClient


def test_custom_field_map_supports_dict_payloads() -> None:
    envelope = SimpleNamespace(
        custom_fields={
            "textCustomFields": [
                {"name": "work_location", "value": "Collier"},
                {"name": "job_title", "value": "Instructional Coach"},
                {"name": "status_change", "value": "New Hire"},
            ]
        }
    )

    result = DocuSignClient._custom_field_map(envelope)

    assert result == {
        "work_location": "Collier",
        "job_title": "Instructional Coach",
        "status_change": "New Hire",
    }


def test_search_envelopes_requests_custom_fields_for_identity_matching() -> None:
    captured: dict[str, str] = {}

    class FakeFoldersApi:
        def __init__(self, _api_client):
            pass

        def search(self, **_kwargs):
            return SimpleNamespace(folder_items=[SimpleNamespace(envelope_id="env-123", status="created")])

    class FakeEnvelopesApi:
        def __init__(self, _api_client):
            pass

        def list_recipients(self, **_kwargs):
            return SimpleNamespace(signers=[SimpleNamespace(email="alice@example.com")])

        def get_envelope(self, **kwargs):
            captured["include"] = str(kwargs.get("include", "") or "")
            return SimpleNamespace(
                custom_fields={
                    "textCustomFields": [
                        {"name": "work_location", "value": "Collier"},
                        {"name": "job_title", "value": "Instructional Coach"},
                        {"name": "status_change", "value": "New Hire"},
                    ]
                }
            )

    client = DocuSignClient()
    with (
        patch("onboarding_agent.integrations.docusign_client.FoldersApi", FakeFoldersApi),
        patch("onboarding_agent.integrations.docusign_client.EnvelopesApi", FakeEnvelopesApi),
        patch.object(client, "_get_api_client", return_value=object()),
    ):
        result = client._search_envelopes_sync(
            "alice@example.com",
            folder_id="drafts",
            count="25",
            require_status="created",
            work_location="Collier",
            job_title="Instructional Coach",
            status_change="New Hire",
        )

    assert captured["include"] == "custom_fields"
    assert result == ("env-123", "created")
