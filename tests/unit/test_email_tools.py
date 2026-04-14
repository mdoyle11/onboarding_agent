"""Tests for email draft persistence via the shared state store."""

from __future__ import annotations

import pytest

from onboarding_agent.mcp_server.tools_email import (
    NS_EMAIL_DRAFTS,
    draft_onboarding_email_for_employee,
    send_clear_to_start_email,
    send_onboarding_email_to_employee,
)
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import FileStateStore


@pytest.mark.asyncio
async def test_email_draft_round_trip_uses_state_store(tmp_path, monkeypatch) -> None:
    previous_store = store_mod.store
    store_mod.store = FileStateStore(str(tmp_path))

    template_path = tmp_path / "onboarding_email.html"
    template_path.write_text("<p>Hello $employee_name</p>", encoding="utf-8")
    attachment_path = tmp_path / "i9.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr("onboarding_agent.mcp_server.tools_email._email_client", lambda: _FakeEmailClient())
    monkeypatch.setattr("onboarding_agent.mcp_server.tools_email.settings.email_template_path", str(template_path))
    monkeypatch.setattr("onboarding_agent.mcp_server.tools_email.settings.i9_documents_attachment_path", str(attachment_path))
    monkeypatch.setattr(
        "onboarding_agent.mcp_server.tools_email.settings.email_subject_template",
        "Welcome, $employee_name!",
    )

    try:
        draft_result = await draft_onboarding_email_for_employee("alice@example.com", "Alice")
        stored = await store_mod.store.get(NS_EMAIL_DRAFTS, "alice@example.com")
        send_result = await send_onboarding_email_to_employee("alice@example.com")
        remaining = await store_mod.store.get(NS_EMAIL_DRAFTS, "alice@example.com")

        assert draft_result["success"] is True
        assert stored is not None
        assert stored["to_email"] == "alice@example.com"
        assert stored["subject"] == "Welcome, Alice!"
        assert send_result["success"] is True
        assert remaining is None
    finally:
        store_mod.store = previous_store


class _FakeEmailClient:
    async def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        attachments: list[dict[str, str]],
    ) -> dict[str, str | bool]:
        assert to_email == "alice@example.com"
        assert subject == "Welcome, Alice!"
        assert "Hello Alice" in body_html
        assert attachments[0]["name"] == "i9.pdf"
        assert attachments[0]["contentType"] == "application/pdf"
        assert attachments[0]["contentBytes"]
        return {"success": True, "message_id": "msg-1"}


@pytest.mark.asyncio
async def test_clear_to_start_email_sends_configured_and_extra_cc(tmp_path, monkeypatch) -> None:
    sent: dict[str, object] = {}
    attachment_path = tmp_path / "List of acceptable I9 documents.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 clear to start")

    class FakeClearToStartEmailClient:
        async def send_email(
            self,
            *,
            to_email: str,
            subject: str,
            body_html: str,
            cc_emails: list[str] | None = None,
            attachments: list[dict[str, str]] | None = None,
        ) -> dict[str, str | bool]:
            sent.update({
                "to_email": to_email,
                "subject": subject,
                "body_html": body_html,
                "cc_emails": cc_emails,
                "attachments": attachments,
            })
            return {"success": True, "message_id": "msg-2"}

    monkeypatch.setattr(
        "onboarding_agent.mcp_server.tools_email._email_client",
        lambda: FakeClearToStartEmailClient(),
    )
    monkeypatch.setattr(
        "onboarding_agent.mcp_server.tools_email.settings.clear_to_start_cc_emails",
        "hr@example.com, ops@example.com",
    )
    monkeypatch.setattr(
        "onboarding_agent.mcp_server.tools_email.settings.i9_documents_attachment_path",
        str(attachment_path),
    )

    result = await send_clear_to_start_email(
        "alice@example.com",
        "Alice Example",
        requested_start_date="2026-08-03",
        treasurer_name="Taylor Treasurer",
        treasurer_email="treasurer@example.com",
        hiring_manager_name="Morgan Manager",
        hiring_manager_email="manager@example.com",
        cc_emails="ops-lead@example.com, hr@example.com",
    )

    assert result["success"] is True
    assert sent["to_email"] == "alice@example.com"
    assert sent["subject"] == "Clear to Start — Alice Example"
    assert "2026-08-03" in str(sent["body_html"])
    assert "Taylor Treasurer" in str(sent["body_html"])
    assert "Morgan Manager" in str(sent["body_html"])
    assert sent["cc_emails"] == [
        "hr@example.com",
        "ops@example.com",
        "ops-lead@example.com",
        "treasurer@example.com",
        "manager@example.com",
    ]
    attachments = sent["attachments"]
    assert isinstance(attachments, list)
    assert attachments[0]["name"] == "List of acceptable I9 documents.pdf"
    assert attachments[0]["contentType"] == "application/pdf"
    assert attachments[0]["contentBytes"]
