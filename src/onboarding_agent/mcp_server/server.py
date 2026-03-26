"""FastMCP server entry point — executed as a stdio subprocess by the agent process."""

import logging

from fastmcp import FastMCP

from onboarding_agent.config import settings
from onboarding_agent.mcp_server.tools_docusign import register as register_docusign
from onboarding_agent.mcp_server.tools_email import register as register_email
from onboarding_agent.mcp_server.tools_graph import register as register_graph
from onboarding_agent.mcp_server.tools_onboarding import register as register_onboarding

logging.basicConfig(level=logging.WARNING)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

_interface = settings.chat_interface.lower()

mcp = FastMCP(
    name="onboarding-tools",
    instructions=(
        f"Tools for HR onboarding: Microsoft Graph (Excel tracker, Forms), "
        f"DocuSign (draft, send, status), email (draft, send), and "
        f"{_interface.capitalize()} notifications. "
        "Use get_onboarding_status for composite queries."
    ),
)

# Always registered — Excel tracker, Forms, DocuSign, email, composite status
register_graph(mcp)
register_docusign(mcp)
register_email(mcp)
register_onboarding(mcp)

# Chat interface tools — only one set is registered based on CHAT_INTERFACE
if settings.is_slack():
    from onboarding_agent.mcp_server.tools_slack import register as register_slack
    register_slack(mcp)
else:
    # Default: Teams (original behaviour)
    from onboarding_agent.mcp_server.tools_graph import register as _  # already registered above
    # Teams notification tools are part of tools_graph — nothing extra to register


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
