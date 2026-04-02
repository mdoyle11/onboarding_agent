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
            patch("onboarding_agent.mcp_server.tools_onboarding._docusign", return_value=self.docusign),
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
    async def test_duplicate_email_returns_disambiguation_summary(self):
        self.tracker.get_employee_stages.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {
                    "row_id": "12",
                    "email": "mdoyle@bridgeprepacademy.com",
                    "location": "Bronx",
                    "job_title": "Teacher",
                    "added_to_tracker": "2026-04-01",
                },
                {
                    "row_id": "15",
                    "email": "mdoyle@bridgeprepacademy.com",
                    "location": "Queens",
                    "job_title": "Assistant Principal",
                    "added_to_tracker": "2026-04-02",
                },
            ],
        }

        from onboarding_agent.mcp_server.tools_onboarding import register
        mcp = FastMCP(name="test-duplicate-status")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "get_onboarding_status")
        result = await tool_fn(employee_email="mdoyle@bridgeprepacademy.com")

        assert result["found"] is False
        assert result["multiple_matches"] is True
        assert "Multiple onboarding records matched" in result["summary"]
        assert "location=Bronx" in result["summary"]
        assert "job_title=Assistant Principal" in result["summary"]

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

        self.tracker.update_stage.assert_awaited_once_with(
            "carol@example.com",
            "Offer Letter Signed",
            location="",
            job_title="",
            status_change="",
        )
        assert result["docusign_status"] == "completed"
        assert result["stages"]["Offer Letter Signed"] == "04/04/2026"


class TestDocuSignTools:
    @pytest.fixture(autouse=True)
    def _patch_clients(self):
        self.tracker = AsyncMock()
        self.docusign = AsyncMock()
        with (
            patch("onboarding_agent.mcp_server.tools_docusign._tracker", return_value=self.tracker),
            patch("onboarding_agent.mcp_server.tools_docusign._docusign", return_value=self.docusign),
        ):
            yield

    @pytest.mark.asyncio
    async def test_check_docusign_draft_exists_surfaces_duplicate_tracker_matches(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {"location": "Collier", "job_title": "Instructional Coach"},
                {"location": "Collier", "job_title": "Assistant Principal"},
            ],
        }
        self.tracker.get_employee_stages.side_effect = [
            {"found": True, "stages": {"Sent Offer Letter": ""}},
            {"found": True, "stages": {"Sent Offer Letter": ""}},
        ]

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "check_docusign_draft_exists")
        result = await tool_fn(employee_email="mdoyle@bridgeprepacademy.com")

        assert result["exists"] is False
        assert result["multiple_matches"] is True
        assert "Multiple tracker rows match this email" in result["error"]
        self.docusign.check_draft_exists.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_docusign_draft_exists_auto_resolves_single_unsent_match(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": False,
            "multiple_matches": True,
            "matches": [
                {
                    "location": "Collier",
                    "job_title": "Instructional Coach",
                    "status_change": "New Hire",
                },
                {
                    "location": "Collier",
                    "job_title": "Assistant Principal",
                    "status_change": "Promotion",
                },
            ],
        }
        self.tracker.get_employee_stages.side_effect = [
            {"found": True, "stages": {"Sent Offer Letter": ""}},
            {"found": True, "stages": {"Sent Offer Letter": "04/01/2026"}},
        ]
        self.docusign.check_draft_exists.return_value = {"exists": True, "envelope_id": "env-123"}

        from onboarding_agent.mcp_server.tools_docusign import register

        mcp = FastMCP(name="test-docusign-autoresolve")
        register(mcp)

        tool_fn = await _get_tool_fn(mcp, "check_docusign_draft_exists")
        result = await tool_fn(employee_email="mdoyle@bridgeprepacademy.com")

        assert result["exists"] is True
        assert result["work_location"] == "Collier"
        assert result["job_title"] == "Instructional Coach"
        assert result["status_change"] == "New Hire"
        self.docusign.check_draft_exists.assert_awaited_once_with(
            "mdoyle@bridgeprepacademy.com",
            "Collier",
            "Instructional Coach",
            "New Hire",
        )


class TestTrackerTools:
    @pytest.fixture(autouse=True)
    def _patch_tracker(self):
        self.tracker = AsyncMock()
        with patch("onboarding_agent.mcp_server.tools_tracker._tracker", return_value=self.tracker):
            yield

    @pytest.mark.asyncio
    async def test_find_employee_in_tracker_returns_compact_payload(self):
        self.tracker.find_employee_in_tracker.return_value = {
            "found": True,
            "row_id": "12",
            "name": "Alice Example",
            "email": "alice@example.com",
            "location": "Bronx",
            "start_date": "2026-04-01",
            "position": "HR",
            "manager_email": "manager@example.com",
            "status": "Sent Offer Letter",
            "stages": {
                "Added to Tracker": "2026-03-01",
                "Sent Offer Letter": "2026-03-02",
            },
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "find_employee_in_tracker")
        result = await tool_fn(employee_email="alice@example.com")

        assert result["found"] is True
        assert result["email"] == "alice@example.com"
        assert result["status"] == "Sent Offer Letter"
        assert "stages" not in result
        assert "Alice Example" in result["summary"]

    @pytest.mark.asyncio
    async def test_list_employees_returns_capped_preview(self):
        employees = []
        for index in range(30):
            employees.append(
                {
                    "name": f"Employee {index}",
                    "email": f"user{index}@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "stages": {"Added to Tracker": "2026-04-01"},
                }
            )
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": employees,
            "count": len(employees),
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-list-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")
        result = await tool_fn(recent_days=0)

        assert result["count"] == 30
        assert result["returned_count"] == 25
        assert result["truncated"] is True
        assert len(result["employees"]) == 25
        assert result["employees"][0]["email"] == "user0@example.com"
        assert "and 5 more" in result["summary"]

    @pytest.mark.asyncio
    async def test_list_employees_defaults_to_recent_30_days(self):
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": [
                {
                    "name": "Recent Hire",
                    "email": "recent@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-03-20",
                    "stages": {"Added to Tracker": "2026-03-20"},
                },
                {
                    "name": "Older Hire",
                    "email": "older@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-01-15",
                    "stages": {"Added to Tracker": "2026-01-15"},
                },
            ],
            "count": 2,
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-recent-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")

        with patch("onboarding_agent.mcp_server.tools_tracker.date") as mock_date:
            from datetime import date as real_date
            mock_date.today.return_value = real_date(2026, 3, 31)
            mock_date.side_effect = real_date
            result = await tool_fn()

        assert result["count"] == 1
        assert result["employees"][0]["email"] == "recent@example.com"
        assert result["recent_days"] == 30

    @pytest.mark.asyncio
    async def test_list_employees_supports_optional_filters(self):
        self.tracker.list_all_employees.return_value = {
            "success": True,
            "employees": [
                {
                    "name": "Bronx Ops",
                    "email": "bronx.ops@example.com",
                    "location": "Bronx",
                    "position": "Ops",
                    "start_date": "2026-03-20",
                    "stages": {"Added to Tracker": "2026-03-20"},
                },
                {
                    "name": "Queens HR",
                    "email": "queens.hr@example.com",
                    "location": "Queens",
                    "position": "HR",
                    "start_date": "2026-03-21",
                    "stages": {"Added to Tracker": "2026-03-21"},
                },
            ],
            "count": 2,
        }

        from onboarding_agent.mcp_server.tools_tracker import register

        mcp = FastMCP(name="tracker-filter-test")
        register(mcp)
        tool_fn = await _get_tool_fn(mcp, "list_employees")
        result = await tool_fn(location="Bronx", position="Ops", recent_days=0)

        assert result["count"] == 1
        assert result["employees"][0]["email"] == "bronx.ops@example.com"
        assert result["location"] == "Bronx"
        assert result["position"] == "Ops"
