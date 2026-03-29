# Onboarding Agent

AI-assisted HR onboarding system for:

- Microsoft Forms / Power Automate
- Microsoft Teams
- Excel via Microsoft Graph
- Outlook via Microsoft Graph
- DocuSign

It receives onboarding events, maintains an Excel-based onboarding tracker,
prepares or sends onboarding communications, and lets HR drive the workflow
from Teams.

## What It Does

| Trigger | Result |
|---|---|
| New-hire Power Automate submission | Adds or checks the employee in the tracker, prepares DocuSign and email steps, posts a Teams card |
| Teams status query | Returns combined tracker + DocuSign onboarding status |
| Teams card button or HR command | Sends the welcome email, sends the offer letter, or performs follow-up steps |
| DocuSign status webhook | Updates tracker state and posts a Teams status update |
| Background-clearance webhook | Updates tracker state, posts a Teams notification, and sends a confirmation email |

## Current Architecture

The current hosted deployment is one Azure Container App running:

- the aiohttp app
- the Teams bot endpoint
- the webhook endpoints
- the Azure Queue-backed background worker
- the FastMCP subprocess used by the LangGraph agent

Durable external state is stored in:

- Azure Queue Storage
- Cosmos DB `state-records`
- Cosmos DB `langgraph-checkpoints`

At runtime, the main layers are:

- `src/onboarding_agent/server.py`
  HTTP app entrypoint and startup

- `src/onboarding_agent/runtime/`
  queueing, webhooks, state store, checkpointing, job handlers

- `src/onboarding_agent/agent/`
  LangGraph state machine and prompt/tool orchestration

- `src/onboarding_agent/mcp_server/`
  FastMCP tool server launched as a subprocess

- `src/onboarding_agent/integrations/`
  Graph, Teams, Outlook, DocuSign, card state

## Docs

- Repo-wide architecture: [ARCHITECTURE.md](/home/matthewdoyle/projects/onboarding_agent/ARCHITECTURE.md)
- Deploy, rollback, smoke test, and CI/CD guidance: [RUNBOOK.md](/home/matthewdoyle/projects/onboarding_agent/RUNBOOK.md)
- Current deployment summary and next steps: [container_app_summary.txt](/home/matthewdoyle/projects/onboarding_agent/container_app_summary.txt)

## Repo Layout

- `src/onboarding_agent/`
  main application package

- `infra/terraform/container-app/`
  Azure Container App Terraform

- `scripts/`
  build, push, deploy, Teams package, roster sync, and cleanup helpers

- `templates/`
  HTML email templates

- `config/`
  example and local config files

- `teamsappPackage.example/`
  commit-safe Teams sideload package template

- `tests/unit/`
  unit tests for queueing, jobs, and webhooks

## Local Quick Start

```bash
uv sync
uv run python -m onboarding_agent.server
```

Before running locally, configure `.env` with:

- Teams / Agents SDK settings
- Azure tenant / client credentials for Graph
- Excel workbook IDs
- Outlook sender mailbox
- DocuSign JWT settings
- webhook secret

For local development, the app can use:

- file-backed state
- local in-process queue
- stdio MCP subprocess

## Hosted Deployment

The hosted deployment uses:

- Docker image from `Dockerfile`
- Terraform in `infra/terraform/container-app/`
- helper scripts in `scripts/`

The main workflow is:

1. Fill `infra/terraform/container-app/terraform.tfvars`
2. Sync staff roster config if needed
3. Build and push an immutable image tag
4. Apply Terraform
5. Update Teams bot endpoint and Teams package if needed
6. Run smoke tests

See:

- [RUNBOOK.md](/home/matthewdoyle/projects/onboarding_agent/RUNBOOK.md)

## Key Scripts

- `scripts/build_and_push_container_app.sh`
  build and push the Container App image

- `scripts/deploy_container_app.sh`
  run Terraform plan/apply

- `scripts/package_teams_app.sh`
  rebuild the Teams sideload package for the current host

- `scripts/sync_staff_rosters_to_tfvars.sh`
  sync local sensitive roster config into `terraform.tfvars`

- `scripts/reset_runtime_state.py`
  clear Cosmos card/conversation state for testing

## Teams Behavior

The primary HR interaction surface is Teams.

Supported patterns:

- DM the bot
- mention the bot in a channel
- click Adaptive Card buttons

The main new-hire card supports:

- `Send Welcome Email`
- `Send Offer Letter`

When DocuSign reaches `completed`, the DocuSign status card supports:

- `Add To Staff Roster`

Card state is persisted so actions can update the original card instead of
posting duplicate follow-ups.

## Staff Roster Config

Staff rosters are configured as one workbook per location.

Preferred local setup:

- keep `config/staff_rosters.json` local and ignored
- use `scripts/sync_staff_rosters_to_tfvars.sh` before deploy

Defaults and examples:

- [.env.example](/home/matthewdoyle/projects/onboarding_agent/.env.example)
- [staff_rosters.example.json](/home/matthewdoyle/projects/onboarding_agent/config/staff_rosters.example.json)

## Adding New Agent Capabilities

The easiest extension point is a new MCP tool in:

- `src/onboarding_agent/mcp_server/tools_*.py`

Example shape:

```python
@mcp.tool()
async def request_it_equipment(employee_email: str, equipment_type: str) -> dict[str, object]:
    ...
```

When adding a new capability, prefer:

- deterministic orchestration for critical system-of-record writes
- agent-driven orchestration for judgment-heavy or optional steps

## Security Notes

- `.env`, `*.key`, `*.pem`, `terraform.tfvars`, and the real `teamsappPackage/`
  are local-only and must not be committed
- webhook endpoints are protected by `WEBHOOK_SECRET`
- Microsoft Graph uses client credentials with tenant-level consent
- DocuSign uses JWT Grant
- sensitive staff roster mappings should remain outside git
