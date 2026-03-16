# Onboarding Agent

A LangGraph-based AI agent that replaces and extends the Power Automate onboarding workflow.

## What it does

| Trigger | Action |
|---|---|
| Power Automate POSTs a new Forms submission | Agent adds employee to Excel tracker → creates DocuSign draft → sends Teams notification |
| HR asks "What's the status of Alice?" in Teams | Agent queries tracker + DocuSign and replies with a human-readable summary |
| HR asks "Send DocuSign for Alice" in Teams | Agent pushes the draft envelope to "sent" |

## Architecture

Two processes communicate via stdio (MCP protocol):

```
aiohttp server (port 8080)
  ├── POST /api/messages        ← Bot Framework Teams messages
  └── POST /webhook/new-hire    ← Power Automate webhook
        │
        └──► LangGraph agent (Claude Sonnet 4.6)
               │
               └──► FastMCP server (stdio subprocess)
                     ├── Microsoft Graph tools (Excel, Teams, Forms)
                     ├── DocuSign tools (draft, send, status)
                     └── Composite tools (get_onboarding_status)
```

## Quick start

```bash
# 1. Clone and install
pip install -r requirements-dev.txt
pip install -e .

# 2. Configure
cp .env.example .env
# Fill in all values — see scripts/setup_azure_ad.py for Azure setup

# 3. Generate DocuSign RSA keys (one time)
python scripts/generate_docusign_keys.py

# 4. Run the server
python -m onboarding_agent.server
```

## Setup guides

- **Azure AD + Bot**: `python scripts/setup_azure_ad.py` — interactive wizard
- **DocuSign JWT**: `python scripts/generate_docusign_keys.py` — generates RSA key pair

## Adding new onboarding steps

Add a function in `src/onboarding_agent/mcp_server/tools_*.py` decorated with `@mcp.tool()`.
The agent picks it up on next restart — no changes to `nodes.py` or `graph.py`.

```python
@mcp.tool()
async def request_it_equipment(employee_email: str, equipment_type: str) -> dict:
    """Submit an IT equipment request for a new hire."""
    ...
```

## Development

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/

# Tests
pytest tests/unit/ -v
```

## Environment variables

See `.env.example` for all required variables with documentation.

## Security notes

- `.env`, `*.key`, `*.pem` are gitignored and must never be committed
- Webhook endpoint is protected by a shared secret (`WEBHOOK_SECRET`)
- DocuSign uses JWT Grant (server-to-server) — no user re-authentication required
- Azure AD uses client credentials flow — admin consent required once per tenant
