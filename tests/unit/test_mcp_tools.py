"""Tests for MCP tool logic with mocked tracker and DocuSign clients."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP


async def _get_tool_fn(mcp: FastMCP, tool_name: str):
    """Extract the raw async function from a FastMCP tool (v3 async API)."""
    tool = await mcp.get_tool(tool_name)
    if tool is None:
        raise KeyError(f"Tool {tool_name!r} not found in MCP registry")
    return tool.fn


# ---------------------------------------------------------------------------
# tools_onboarding.get_onboarding_status
# ---------------------------------------------------------------------------

class TestGetOnboardingStatus:
    @pytest.fixture(autouse=True)
    def _patch_clients(self):
        self.tracker = AsyncMock()
        self.docusign = AsyncMock()
        self.docusign.find_latest_envelope_for_employee.return_value = {
            "found": False,
            "envelope_id": "",
            "status": "",
        }

        with (
            patch("onboarding_agent.mcp_server.tools_onboarding._tracker", return_value=self.tracker),
            patch("onboarding_agent.mcp_server.tools_onboarding.DocuSignClient", return_value=self.docusign),
        ):
            yield

    @pytest.mark.asyncio
    async def test_not_found_returns_found_false(self):
        self.tracker.find_employee_in_tracker.return_value = {"found": False}
        self.tracker.get_employee_stages.return_value = {"found": False}

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="nobody@example.com")

        assert result["found"] is False
        assert "No onboarding record found" in result["summary"]

    @pytest.mark.asyncio
    async def test_found_with_draft_envelope(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "3", "name": "Alice",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "",
                "Sent Offer Letter": "",
                "Offer Letter Signed": "",
            },
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-123"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "created", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test2")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert result["docusign_status"] == "created"
        assert "draft has been created but not yet sent" in result["summary"]
        assert "Added to Staff Roster: pending" in result["summary"]

    @pytest.mark.asyncio
    async def test_found_with_completed_envelope(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "4", "name": "Bob",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "2026-04-02",
                "Sent Offer Letter": "2026-04-03",
                "Offer Letter Signed": "2026-04-04",
            },
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-456"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "completed", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test3")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="bob@example.com")

        assert result["docusign_status"] == "completed"
        assert "fully signed" in result["summary"]

    @pytest.mark.asyncio
    async def test_completed_envelope_reconciles_missing_signed_stage(self):
        self.tracker.get_employee_stages.return_value = {
            "found": True, "row_id": "5", "name": "Carol",
            "stages": {
                "Added to Tracker": "2026-04-01",
                "Added to Staff Roster": "2026-04-02",
                "Sent Offer Letter": "2026-04-03",
                "Offer Letter Signed": "",
            },
        }
        self.tracker.update_stage.return_value = {
            "success": True,
            "employee_email": "carol@example.com",
            "stage": "Offer Letter Signed",
            "value": "2026-04-04",
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": False, "envelope_id": ""
        }
        self.docusign.find_latest_envelope_for_employee.return_value = {
            "found": True, "envelope_id": "env-789", "status": "completed"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "completed", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test4")
        register(mcp)

        with (
            patch("onboarding_agent.mcp_server.tools_onboarding.get_docusign_status_card", new=AsyncMock(return_value=None)),
            patch("onboarding_agent.mcp_server.tools_onboarding.save_docusign_status_card", new=AsyncMock()),
            patch("onboarding_agent.integrations.teams.messenger.TeamsMessenger.send_channel_notification", new=AsyncMock(return_value={"success": True, "message_id": "msg-1"})),
        ):
            tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
            result = await tool_fn(employee_email="carol@example.com")

        self.tracker.update_stage.assert_awaited_once_with("carol@example.com", "Offer Letter Signed")
        assert result["docusign_status"] == "completed"
        assert result["stages"]["Offer Letter Signed"] == "04/04/2026"
