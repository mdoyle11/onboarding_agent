# Onboarding Agent

A LangGraph-based AI agent for the Microsoft onboarding stack: Microsoft Forms, Power Automate, Teams, Excel via Microsoft Graph, Outlook, and DocuSign.

## What it does

| Trigger | Action |
|---|---|
| Power Automate POSTs a new Microsoft Forms submission | Agent adds the employee to the Excel tracker, creates a DocuSign draft, drafts the onboarding email, and posts a Teams Adaptive Card |
| HR asks "What's the status of Alice?" in Teams | Agent queries Excel + DocuSign and replies with a human-readable summary |
| HR asks to send the offer letter or clicks the card action | Agent sends the DocuSign envelope and updates the original Teams card |
| HR asks to send the welcome email or clicks the card action | Agent sends the Outlook email and updates the original Teams card |

## Architecture

Two processes communicate via stdio using MCP:

```text
aiohttp server (port 8080)
  ├── GET/POST /api/messages              ← Microsoft 365 Agents SDK / Teams
  ├── POST /webhook/new-hire              ← Power Automate
  ├── POST /webhook/docusign              ← DocuSign Connect
  └── POST /webhook/background-clearance  ← Power Automate
        │
        └──► LangGraph agent
               │
               └──► FastMCP server (stdio subprocess)
                     ├── Microsoft Graph tools (Excel, Teams, Forms, Outlook)
                     ├── DocuSign tools
                     └── Composite onboarding/status tools
```

## Current stack

- Chat interface: Microsoft Teams via Microsoft 365 Agents SDK
- Tracker backend: Excel workbook via Microsoft Graph
- Email backend: Outlook via Microsoft Graph `sendMail`
- Signature backend: DocuSign JWT + DocuSign Connect
- Workflow source: Microsoft Forms + Power Automate webhooks
- Notification UX: Teams Adaptive Cards with action-state sync

## Quick start

```bash
# 1. Install dependencies
uv sync

# 2. Configure .env with Microsoft Graph, Teams, Outlook, and DocuSign settings

# 3. Generate DocuSign RSA keys if needed
python scripts/generate_docusign_keys.py

# 4. Run the server
uv run python -m onboarding_agent.server
```

## Setup guides

- Azure / Microsoft Graph app registration: `python scripts/setup_azure_ad.py`
- Teams / Agents SDK app registration: `python scripts/setup_azure_bot.py`
- DocuSign JWT keys: `python scripts/generate_docusign_keys.py`

## Teams card actions

The new-hire Teams card supports:

- `Send Welcome Email`
- `Send Offer Letter`

When one of those actions succeeds, the original card is updated to show completion so teammates do not send the same step twice. Natural-language sends from a DM, group chat, or channel message also update the original card in the notification channel.

## Adding new onboarding steps

Add a function in `src/onboarding_agent/mcp_server/tools_*.py` decorated with `@mcp.tool()`.
The agent picks it up on next restart.

```python
@mcp.tool()
async def request_it_equipment(employee_email: str, equipment_type: str) -> dict:
    """Submit an IT equipment request for a new hire."""
    ...
```

## Development

```bash
uv run pytest tests/unit -q
```

## Environment

This branch expects Microsoft-only configuration:

- Teams / Agents SDK app ID and secret
- Azure tenant / client credentials for Graph
- Excel workbook IDs
- Outlook sender mailbox
- DocuSign JWT settings
- webhook secret

## Security notes

- `.env`, `*.key`, and `*.pem` are gitignored and must never be committed
- Webhook endpoints are protected by `WEBHOOK_SECRET`
- Microsoft Graph uses client credentials flow and requires admin consent once per tenant
- DocuSign uses JWT Grant for server-to-server access
