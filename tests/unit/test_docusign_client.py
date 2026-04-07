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


def test_create_envelope_draft_includes_submission_id_custom_field() -> None:
    captured: dict[str, object] = {}

    class FakeEnvelopesApi:
        def __init__(self, _api_client):
            pass

        def create_envelope(self, **kwargs):
            captured["envelope_definition"] = kwargs["envelope_definition"]
            return SimpleNamespace(envelope_id="env-123", status="created")

    client = DocuSignClient()
    with (
        patch("onboarding_agent.integrations.docusign_client.EnvelopesApi", FakeEnvelopesApi),
        patch.object(client, "_get_api_client", return_value=object()),
        patch("onboarding_agent.integrations.docusign_client.settings.docusign_connect_url", ""),
        patch("onboarding_agent.integrations.docusign_client.settings.docusign_template_id", "template-1"),
        patch("onboarding_agent.integrations.docusign_client.settings.docusign_account_id", "account-1"),
    ):
        result = client._create_envelope_draft_sync(
            employee_name="Alice Example",
            employee_email="alice@example.com",
            start_date="2026-04-10",
            position="Teacher",
            work_location="Bronx",
            status_change="New Hire",
            submission_id="sub-123",
        )

    assert result["success"] is True
    envelope_definition = captured["envelope_definition"]
    custom_fields = envelope_definition.custom_fields["textCustomFields"]
    assert any(field["name"] == "submission_id" and field["value"] == "sub-123" for field in custom_fields)
    signer_tabs = envelope_definition.template_roles[0].tabs.text_tabs
    start_date_tab = next(tab for tab in signer_tabs if tab.tab_label == "StartDate")
    assert start_date_tab.value == "04/10/2026"


def test_delete_draft_envelope_moves_created_envelope_to_deleted_folder() -> None:
    captured: dict[str, object] = {}

    class FakeEnvelopesApi:
        def __init__(self, _api_client):
            pass

        def get_envelope(self, **kwargs):
            if kwargs.get("include") == "custom_fields":
                return SimpleNamespace(
                    status="created",
                    custom_fields={
                        "textCustomFields": [
                            {"name": "employee_email", "value": "alice@example.com"},
                            {"name": "work_location", "value": "Bronx"},
                            {"name": "job_title", "value": "Teacher"},
                            {"name": "status_change", "value": "New Hire"},
                            {"name": "submission_id", "value": "sub-123"},
                        ]
                    },
                )
            return SimpleNamespace(status="created")

        def list_recipients(self, **_kwargs):
            return SimpleNamespace(signers=[SimpleNamespace(email="alice@example.com", name="Alice Example")])

    class FakeFoldersApi:
        def __init__(self, _api_client):
            pass

        def list(self, **_kwargs):
            return SimpleNamespace(
                folders=[
                    SimpleNamespace(folder_id="drafts-1", type="draft", name="Drafts"),
                    SimpleNamespace(folder_id="deleted-1", type="deletedItems", name="Deleted Items"),
                ]
            )

        def move_envelopes(self, **kwargs):
            captured["folder_id"] = kwargs["folder_id"]
            captured["folders_request"] = kwargs["folders_request"]
            return SimpleNamespace()

    client = DocuSignClient()
    with (
        patch("onboarding_agent.integrations.docusign_client.EnvelopesApi", FakeEnvelopesApi),
        patch("onboarding_agent.integrations.docusign_client.FoldersApi", FakeFoldersApi),
        patch.object(client, "_get_api_client", return_value=object()),
        patch("onboarding_agent.integrations.docusign_client.settings.docusign_account_id", "account-1"),
    ):
        result = client._delete_draft_envelope_sync("env-123")

    assert result["success"] is True
    assert result["envelope_id"] == "env-123"
    assert result["status"] == "deleted"
    assert result["employee_email"] == "alice@example.com"
    assert result["employee_name"] == "Alice Example"
    assert captured["folder_id"] == "deleted-1"
    folders_request = captured["folders_request"]
    assert folders_request.envelope_ids == ["env-123"]
    assert folders_request.from_folder_id == "drafts-1"


def test_list_draft_envelopes_returns_filtered_preview() -> None:
    class FakeEnvelopesApi:
        def __init__(self, _api_client):
            pass

        def get_envelope(self, **kwargs):
            envelope_id = kwargs["envelope_id"]
            if envelope_id == "env-1":
                return SimpleNamespace(
                    status="created",
                    custom_fields={"textCustomFields": [
                        {"name": "employee_email", "value": "alice@example.com"},
                        {"name": "work_location", "value": "Bronx"},
                        {"name": "job_title", "value": "Teacher"},
                        {"name": "status_change", "value": "New Hire"},
                    ]},
                )
            return SimpleNamespace(
                status="created",
                custom_fields={"textCustomFields": [
                    {"name": "employee_email", "value": "bob@example.com"},
                    {"name": "work_location", "value": "Collier"},
                    {"name": "job_title", "value": "Coach"},
                    {"name": "status_change", "value": "Transfer In"},
                ]},
            )

        def list_recipients(self, **kwargs):
            envelope_id = kwargs["envelope_id"]
            if envelope_id == "env-1":
                return SimpleNamespace(signers=[SimpleNamespace(email="alice@example.com", name="Alice Example")])
            return SimpleNamespace(signers=[SimpleNamespace(email="bob@example.com", name="Bob Example")])

    class FakeFoldersApi:
        def __init__(self, _api_client):
            pass

        def search(self, **_kwargs):
            return SimpleNamespace(
                folder_items=[
                    SimpleNamespace(envelope_id="env-1", status="created", created_date_time="2026-04-03T20:00:00Z"),
                    SimpleNamespace(envelope_id="env-2", status="created", created_date_time="2026-04-03T21:00:00Z"),
                ]
            )

    client = DocuSignClient()
    with (
        patch("onboarding_agent.integrations.docusign_client.EnvelopesApi", FakeEnvelopesApi),
        patch("onboarding_agent.integrations.docusign_client.FoldersApi", FakeFoldersApi),
        patch.object(client, "_get_api_client", return_value=object()),
        patch("onboarding_agent.integrations.docusign_client.settings.docusign_account_id", "account-1"),
    ):
        result = client._list_draft_envelopes_sync(employee_email="alice@example.com", limit=5)

    assert result["total_count"] == 1
    assert result["drafts"] == [
        {
            "envelope_id": "env-1",
            "employee_email": "alice@example.com",
            "employee_name": "Alice Example",
            "work_location": "Bronx",
            "job_title": "Teacher",
            "status_change": "New Hire",
            "submission_id": "",
            "status": "created",
            "created_date_time": "2026-04-03T20:00:00Z",
        }
    ]
