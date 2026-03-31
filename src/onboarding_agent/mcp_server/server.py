"""FastMCP server entry point — executed as a stdio subprocess by the agent process."""

import logging

from fastmcp import FastMCP

from onboarding_agent.config import settings
from onboarding_agent.mcp_server.tools_docusign import register as register_docusign
from onboarding_agent.mcp_server.tools_email import register as register_email
from onboarding_agent.mcp_server.tools_onboarding import register as register_onboarding
from onboarding_agent.mcp_server.tools_staff_roster import register as register_staff_roster
from onboarding_agent.mcp_server.tools_teams import register as register_teams
from onboarding_agent.mcp_server.tools_tracker import register as register_tracker
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import create_state_store

logging.basicConfig(level=logging.WARNING)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)


def _initialize_runtime() -> None:
    """Initialize shared runtime dependencies needed by MCP tools."""
    if store_mod.store is None:
        store_mod.store = create_state_store(
            backend=settings.state_store_backend,
            state_store_dir=settings.state_store_dir,
            cosmos_endpoint=settings.cosmos_endpoint,
            cosmos_key=settings.cosmos_key,
            cosmos_database_name=settings.cosmos_database_name,
            cosmos_container_name=settings.cosmos_container_name,
        )

mcp = FastMCP(
    name="onboarding-tools",
    instructions=(
        "Tools for HR onboarding: Microsoft Graph (Excel tracker, Forms), "
        "staff roster capacity and roster updates, "
        "DocuSign (draft, send, status), Outlook email (draft, send), and "
        "Teams notifications. "
        "Use get_onboarding_status for composite queries."
    ),
)

# Always registered — tracker, roster, Forms, DocuSign, email, Teams, composite status
register_tracker(mcp)
register_staff_roster(mcp)
register_docusign(mcp)
register_email(mcp)
register_teams(mcp)
register_onboarding(mcp)


def main() -> None:
    _initialize_runtime()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
