"""Tests for email draft persistence via the shared state store."""

from __future__ import annotations

import pytest

from onboarding_agent.mcp_server.tools_email import (
    NS_EMAIL_DRAFTS,
    draft_onboarding_email_for_employee,
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

    monkeypatch.setattr("onboarding_agent.mcp_server.tools_email._email_client", lambda: _FakeEmailClient())
    monkeypatch.setattr("onboarding_agent.mcp_server.tools_email.settings.email_template_path", str(template_path))
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
    async def send_email(self, *, to_email: str, subject: str, body_html: str) -> dict[str, str | bool]:
        assert to_email == "alice@example.com"
        assert subject == "Welcome, Alice!"
        assert "Hello Alice" in body_html
        return {"success": True, "message_id": "msg-1"}
