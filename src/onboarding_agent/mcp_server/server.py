"""FastMCP server entry point — executed as a stdio subprocess by the agent process."""

import logging

from fastmcp import FastMCP

from onboarding_agent.mcp_server.tools_docusign import register as register_docusign
from onboarding_agent.mcp_server.tools_email import register as register_email
from onboarding_agent.mcp_server.tools_graph import register as register_graph
from onboarding_agent.mcp_server.tools_onboarding import register as register_onboarding

logging.basicConfig(level=logging.WARNING)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

mcp = FastMCP(
    name="onboarding-tools",
    instructions=(
        f"Tools for HR onboarding: Microsoft Graph (Excel tracker, Forms), "
        "DocuSign (draft, send, status), Outlook email (draft, send), and "
        "Teams notifications. "
        "Use get_onboarding_status for composite queries."
    ),
)

# Always registered — Excel tracker, Forms, DocuSign, email, composite status
register_graph(mcp)
register_docusign(mcp)
register_email(mcp)
register_onboarding(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
