"""FastMCP server entry point — executed as a stdio subprocess by the agent process."""

import logging

from fastmcp import FastMCP

from onboarding_agent.mcp_server.tools_docusign import register as register_docusign
from onboarding_agent.mcp_server.tools_graph import register as register_graph
from onboarding_agent.mcp_server.tools_onboarding import register as register_onboarding

logging.basicConfig(level=logging.WARNING)

mcp = FastMCP(
    name="onboarding-tools",
    instructions=(
        "Tools for HR onboarding: Microsoft Graph (Excel tracker, Teams, Forms) "
        "and DocuSign (draft, send, status). Use get_onboarding_status for composite queries."
    ),
)

# Register all tool groups
register_graph(mcp)
register_docusign(mcp)
register_onboarding(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
