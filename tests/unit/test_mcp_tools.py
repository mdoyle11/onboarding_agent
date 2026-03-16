"""Tests for MCP tool logic with mocked Graph/DocuSign clients."""

import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# tools_onboarding.get_onboarding_status
# ---------------------------------------------------------------------------

class TestGetOnboardingStatus:
    @pytest.fixture(autouse=True)
    def _patch_clients(self):
        with (
            patch("onboarding_agent.mcp_server.tools_onboarding.GraphClient") as gc,
            patch("onboarding_agent.mcp_server.tools_onboarding.DocuSignClient") as dc,
        ):
            self.graph = AsyncMock()
            self.docusign = AsyncMock()
            gc.return_value = self.graph
            dc.return_value = self.docusign
            yield

    @pytest.mark.asyncio
    async def test_not_found_returns_found_false(self):
        self.graph.find_employee_in_tracker.return_value = {"found": False}

        from onboarding_agent.mcp_server.tools_onboarding import register
        from fastmcp import FastMCP
        mcp = FastMCP(name="test")
        register(mcp)

        # Call the function directly via the registered tool's underlying function
        # We access the wrapped function through FastMCP's tool registry
        tool_fn = _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="nobody@example.com")

        assert result["found"] is False
        assert "No onboarding record found" in result["summary"]

    @pytest.mark.asyncio
    async def test_found_with_draft_envelope(self):
        self.graph.find_employee_in_tracker.return_value = {
            "found": True, "row_id": "3", "status": "Pending"
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-123"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "created", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        from fastmcp import FastMCP
        mcp = FastMCP(name="test2")
        register(mcp)

        tool_fn = _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert result["docusign_status"] == "created"
        assert "draft has been created but not yet sent" in result["summary"]

    @pytest.mark.asyncio
    async def test_found_with_completed_envelope(self):
        self.graph.find_employee_in_tracker.return_value = {
            "found": True, "row_id": "4", "status": "Completed"
        }
        self.docusign.check_draft_exists.return_value = {
            "exists": True, "envelope_id": "env-456"
        }
        self.docusign.get_envelope_status.return_value = {
            "status": "completed", "recipients": []
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        from fastmcp import FastMCP
        mcp = FastMCP(name="test3")
        register(mcp)

        tool_fn = _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="bob@example.com")

        assert result["docusign_status"] == "completed"
        assert "fully signed" in result["summary"]


def _get_tool_fn(mcp, tool_name):
    """Extract the raw async function from a FastMCP tool registry."""
    # FastMCP stores tools in ._tool_manager or similar; access varies by version
    # Fall back to iterating registered tools
    for name, tool in mcp._tool_manager._tools.items():
        if name == tool_name:
            return tool.fn
    raise KeyError(f"Tool {tool_name!r} not found in MCP registry")
