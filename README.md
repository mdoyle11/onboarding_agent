# Onboarding Agent

> Originally a personal project; now adopted and in production use at a former employer.

AI-assisted HR onboarding system. The agent listens for new-hire events, drives an Excel-based onboarding tracker, sends offer letters via DocuSign, sends onboarding emails via Outlook, and lets HR run the workflow conversationally from Microsoft Teams.

Surfaces wired in:

- Microsoft Forms / Power Automate (intake webhook)
- Microsoft Teams (HR conversation surface + adaptive cards)
- Microsoft Graph (Excel tracker, staff rosters, Outlook mail)
- DocuSign (offer letters via JWT Grant + Connect webhooks)

## What it does

| Trigger | Result |
|---|---|
| New-hire Power Automate submission | Upserts the tracker row, prepares DocuSign and email steps, posts a Teams card |
| Teams status query | Returns combined tracker + DocuSign status |
| Teams card button or HR command | Sends the welcome email, sends the offer letter, performs follow-up steps |
| DocuSign Connect event | Updates tracker state, refreshes the status card, posts a Teams notification |
| Background-clearance webhook | Updates tracker state, posts a Teams notification, sends the confirmation email |

## Architecture (one paragraph)

One `aiohttp` process (deployed as a single Azure Container App) serves the Teams bot endpoint, three webhook endpoints, a background worker that drains an Azure Storage Queue, and a FastMCP subprocess that hosts the agent's tools. State lives in Cosmos DB (workflow + Teams session state) and Excel via Graph (tracker / rosters / separations — the system of record). Detailed walkthrough: [`docs/walkthrough/ARCHITECTURE.md`](docs/walkthrough/ARCHITECTURE.md).

## Repo layout

- `src/onboarding_agent/` — application package
  - `server.py` — aiohttp entrypoint, route wiring, startup
  - `runtime/` — webhooks, job queue, state store, job handlers
  - `agent/` — LangChain agent runner + session context
  - `mcp_server/` — FastMCP tool server (one `tools_*.py` per capability area)
  - `integrations/` — Graph, Teams, Outlook, DocuSign, adaptive cards, card state
  - `domain/` — pure rules (workflows, identity, per-workflow policies)
  - `observability/` — OpenTelemetry setup, PII redaction, evals
- `infra/terraform/foundation/` — shared platform (RG, ACR, Container Apps env, Cosmos, Storage, Key Vault, managed identity, Azure OpenAI, Bot)
- `infra/terraform/app/` — Container App + app-specific Cosmos containers + Storage queue
- `scripts/` — setup wizards, build/push, Teams packaging, roster sync, state reset
- `templates/` — HTML email templates
- `config/` — example + local config files (real `staff_rosters.json` is local-only)
- `teamsappPackage.example/` — commit-safe Teams sideload template
- `tests/unit/` — unit tests
- `evals/` — deterministic regression eval suite (runs in CI)
- `loadtest/` — k6 scaffolds for webhook + Teams load testing
- `docs/walkthrough/` — deeper architecture + runbook + interactive explorer

## Local quick start

```bash
uv sync
cp .env.example .env
# fill in values (see docs/walkthrough/RUNBOOK.md section 2)

uv run python -m onboarding_agent.server
```

Local defaults need no Azure resources:

- `STATE_STORE_BACKEND=file`
- `JOB_QUEUE_BACKEND=local`
- `OBSERVABILITY_ENABLED=false`

Lint / test / evals:

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/unit/ -v
uv run python -m evals.run
```

## Hosted deployment (high level)

1. Apply `infra/terraform/foundation/` to provision shared platform resources (once per environment).
2. Build and push the container image: `scripts/build_and_push_container_app.sh <acr-name> <image-tag>`.
3. Populate `infra/terraform/app/terraform-<env>.tfvars` with the foundation outputs + the new image tag.
4. `scripts/sync_staff_rosters_to_tfvars.sh infra/terraform/app/terraform-<env>.tfvars` if your roster mapping changed.
5. `terraform apply` in `infra/terraform/app/`.
6. Re-package the Teams app if the bot host changed: `scripts/package_teams_app.sh <bot-host> <bot-app-id>`.
7. Run smoke tests (see runbook section 8).

Full step-by-step: [`docs/walkthrough/RUNBOOK.md`](docs/walkthrough/RUNBOOK.md).

## Teams behavior

Primary HR surface is Teams (DM the bot, mention it in a channel, or click adaptive-card buttons).

Cards supported today:

- **New-hire card** — `Send Welcome Email`, `Send Offer Letter`
- **DocuSign status card** — `Add To Staff Roster` once the envelope reaches `completed`
- **Offboarding** / **temporary-staff** / **background-clearance** cards — workflow-specific actions

Card state is persisted in Cosmos so a button click updates the existing card instead of posting a duplicate.

## Adding new agent capabilities

The smallest extension point is a new MCP tool:

```python
# src/onboarding_agent/mcp_server/tools_<area>.py
@mcp.tool()
async def request_it_equipment(employee_email: str, equipment_type: str) -> dict[str, object]:
    ...
```

The LangChain runner discovers tools from the MCP client at startup — no changes to the runner, runtime, or graph wiring needed. See `ARCHITECTURE.md` section "Extension points" for the four extension surfaces (new tool / new webhook / new external system / new workflow type).

## Security notes

- `.env`, `*.key`, `*.pem`, `terraform.tfvars`, and the real `teamsappPackage/` are local-only and must not be committed.
- Webhook endpoints accept an `X-Webhook-Secret` header validated against `WEBHOOK_SECRET` (DocuSign Connect is trusted by source and does not use this header).
- Microsoft Graph uses client credentials with tenant-level admin consent.
- DocuSign uses JWT Grant with a 2048-bit RSA key pair.
- Sensitive secrets in production live in Key Vault (`webhook_secret`, `microsoft_app_password`, `azure_client_secret`, `docusign_private_key`) and are surfaced to the Container App as Key Vault-backed secrets.

## Not included in this repo

The production deployment also integrates with ADP's APIs for HRIS functions. That code is not published here as ADP API access is gated and the integration is too org-specific to be useful as a reference.

## Documentation

- Deeper architecture walkthrough: [`docs/walkthrough/ARCHITECTURE.md`](docs/walkthrough/ARCHITECTURE.md)
- Operational runbook (setup → deploy → observe → rotate → roll back): [`docs/walkthrough/RUNBOOK.md`](docs/walkthrough/RUNBOOK.md)
- Interactive module explorer: `docs/walkthrough/react-architecture-explorer/`
