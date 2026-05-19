# Architecture

A deeper walkthrough of the onboarding agent than the top-level `README.md`. The goal is to show how the modules fit together — from inbound HTTP traffic, through the agent loop, out to the Microsoft 365 / DocuSign world — and where state lives.

For the interactive view of the same material, see `docs/walkthrough/react-architecture-explorer/` and `docs/walkthrough/flowcharts/onboarding-agent-function-graphs.html`.

## At a glance

One Azure Container App runs a single `aiohttp` process. That process owns:

- the Teams bot endpoint (`POST /api/messages`)
- three webhook endpoints (new-hire, DocuSign, background-clearance)
- a background queue worker
- a stdio-launched FastMCP subprocess that hosts the agent's tools

External state lives in:

- Azure Storage Queue — durable job buffer between webhook intake and side effects
- Cosmos DB `state-records` — adaptive-card and workflow state, keyed by employee identity
- Cosmos DB `conversation-sessions` — Teams thread → session context (last referenced employee, workflow, etc.)
- Excel workbooks via Microsoft Graph — the tracker, separations sheet, and per-location staff rosters (system of record)
- DocuSign — offer letters and signing state

The agent never persists anything itself. All durable state goes through one of the stores above.

## Process topology

```
                    +---------------------------+
   Teams ──────────►│  POST /api/messages       │
                    │  (Microsoft 365 Agents    │
                    │   SDK + CloudAdapter)     │
                    +─────────────┬─────────────+
                                  │
                                  ▼
Power Automate ───►  POST /webhook/new-hire           ┐
DocuSign Connect ─►  POST /webhook/docusign           ├──► JobQueue ──► process_job(...)
Background svc ───►  POST /webhook/background-clearance ┘     │
                                                              │
                                                              ▼
                                                  Tracker / Roster / Email /
                                                  DocuSign / Teams side effects
                                                              │
                          ┌───────────────────────────────────┘
                          ▼
                   +-------------+        stdio        +----------------------+
                   │ agent/runner │ ◄──────────────────►│ mcp_server (FastMCP) │
                   +-------------+                     +----------------------+
                          │                                   │
                          ▼                                   ▼
                Anthropic / Gemini /              Graph Excel, Outlook,
                Azure OpenAI                      DocuSign, Teams clients
```

The Teams path and the webhook path are independent at the HTTP layer; they only meet at the side-effect layer (tracker writes, card updates, email/DocuSign sends).

## Module map

### `src/onboarding_agent/server.py`
aiohttp entrypoint.

- `create_app()` wires routes and lifecycle handlers.
- `_setup_teams()` initializes the Microsoft 365 Agents SDK (`MsalConnectionManager`, `CloudAdapter`, `AgentApplication`) and registers the Teams handlers from `integrations/teams/bot.py`.
- `_on_startup()` creates the state store, primes the LangChain agent (`runner.initialize`), and starts the job queue. `_on_cleanup()` drains it.
- Three webhook routes are mounted in `create_app()`; their handlers live in `runtime/webhooks.py`.

### `src/onboarding_agent/config.py`
`pydantic-settings` validated config, loaded from `.env` / Container App env. One module-level `settings` singleton is imported everywhere — there is no separate dependency-injection layer. New env vars are added here, then read by feature modules.

### `src/onboarding_agent/runtime/`
Everything that turns inbound events into durable, retryable work.

- `webhooks.py` — parses payloads (JSON or DocuSign XML), validates the shared secret, enqueues a `QueueJob`, returns `202`-style ack. Webhook handlers never do side effects directly; they hand off to the queue.
- `job_queue.py` — `JobQueue` protocol with two implementations:
  - `LocalJobQueue` (in-process `asyncio` tasks) for local dev
  - `AzureStorageJobQueue` for the deployed Container App
  Selected by `JOB_QUEUE_BACKEND`.
- `jobs.py` — the single `process_job(QueueJob)` dispatcher and the three concrete handlers (`process_new_hire_job`, `process_docusign_job`, `process_background_clearance_job`). This is the largest module in the codebase and is where the deterministic onboarding orchestration lives: figure out workflow type (new-hire / rehire / offboarding / temp), upsert the tracker, choose the right adaptive card, send or update it, schedule emails, and record card state.
- `payloads.py` — small helpers that tolerate the different shapes Power Automate and DocuSign send.
- `state_store.py` / `state_store_cosmos.py` — `StateStore` protocol with `FileStateStore` (local dev) and `CosmosStateStore`. Selected by `STATE_STORE_BACKEND`. Two store instances are created at startup: one for workflow/card state, one for Teams session context.

The pluggable queue and store abstractions are intentional — they let the same code run locally without Azure, and they make the eventual split into separate worker/web tiers cheap.

### `src/onboarding_agent/agent/`
The LangChain agent that powers HR's natural-language Teams interactions.

- `runner.py` — `initialize()` builds the LLM (`langchain-anthropic`, Gemini, or Azure OpenAI per `LLM_PROVIDER`) and connects to the MCP subprocess via `langchain-mcp-adapters` (`MultiServerMCPClient`). `run_agent(...)` is the main loop: trim history → call LLM → execute any tool calls via MCP → repeat up to `_MAX_TOOL_LOOPS`. The system prompt encodes the routing rules (when to use which tool, what to reuse from session context).
- `session_context.py` — derives a small structured context (employee email, work location, job category, submission_id, etc.) from the most recent thread messages and Cosmos session record. This is what lets follow-up questions in a Teams thread skip re-asking for the employee.

The agent does not own state. Persistence is in Cosmos via the runtime state store; the agent reads a session record at the start of each turn and writes back the trimmed history at the end.

### `src/onboarding_agent/mcp_server/`
FastMCP server launched as a stdio subprocess. Each `tools_*.py` module registers a group of `@mcp.tool()` functions with `mcp`:

- `tools_tracker.py` — Excel tracker reads/writes (find, update, stage transitions)
- `tools_staff_roster.py` — per-location roster CRUD + vacancy queries
- `tools_separations.py` — separations sheet
- `tools_docusign.py` — DocuSign drafts, sends, status, document download
- `tools_email.py` — Outlook draft/send
- `tools_teams.py` — Teams proactive messages / card updates
- `tools_onboarding.py` — composite tools that span the above (e.g. `get_onboarding_status`, `create_offer_letter_draft_from_tracker`)

**Extension point.** Adding a new agent capability almost always means adding a new `@mcp.tool()` here. `nodes.py`/`graph.py` no longer exist — the LangChain runner is the orchestrator and just discovers tools from the MCP client. The runtime job handlers are unaffected.

`clients.py` builds the Graph/DocuSign/Outlook clients with shared auth.

### `src/onboarding_agent/integrations/`
The thin client layer that the runtime *and* the MCP tools call into. Both sides share the same clients so behavior stays consistent.

- `graph/auth.py` — Microsoft Graph client-credentials auth (tenant-level consent app registration).
- `workbook/` — Excel-as-database. `client.py` is the generic table client; `tracker_client.py`, `staff_roster_client.py`, `separations_client.py` are domain wrappers. `schema.py` declares the relaxed-field-name resolution rules (so "stage" vs "Stage" vs "stage_name" all hit the right column).
- `outlook_email_client.py` — sends HTML email via Graph using `templates/*.html`.
- `docusign_client.py` — JWT Grant auth + envelope CRUD + Connect-event helpers.
- `teams/` — proactive messaging, mention parsing, adaptive-card actions, and Agents-SDK turn handlers (`bot.py`, `runtime.py`).
- `adaptive_cards.py` — builders for the new-hire, offboarding, temporary, background-check, and DocuSign cards.
- `card_state.py` — the bridge between adaptive cards and the Cosmos state store: which card is currently showing for which employee/workflow, and which actions are still available.

### `src/onboarding_agent/domain/`
Pure rules with no I/O. This is where workflow shape lives:

- `workflows.py` — workflow type constants and normalization (`new_hire`, `rehire`, etc.).
- `identity.py` — `EmployeeIdentity` (the composite key used across tracker, cards, and DocuSign).
- `field_resolution.py` / `formatting.py` — relaxed-name resolution and value formatting shared by the tracker and roster clients.
- `onboard/policies.py`, `offboard/policies.py`, `temp/policies.py` — per-workflow rules (which tracker stages are excluded, which card actions are allowed, which roster behavior applies).

Domain modules are imported by both `runtime/jobs.py` and the MCP tools. They never import from `integrations/` or `runtime/`.

### `src/onboarding_agent/observability/`
- `setup.py` — OpenTelemetry tracer/meter configuration (OTLP exporter is optional; falls back to stdout in dev).
- `tracing.py` — `start_span(...)` context manager used across server, runtime, agent, and integrations.
- `evals.py` — regression-eval span hooks (used by `evals/`).
- `pii.py` — redaction helpers for log output and span attributes.

## Request lifecycles

### Teams chat → answer
1. Teams sends the activity to `POST /api/messages`.
2. The Agents SDK adapter authenticates and routes it to the handlers registered in `integrations/teams/bot.py`.
3. The handler reads (or creates) the Cosmos `conversation-sessions` record for this thread and derives a `SessionContext`.
4. It calls `agent.runner.run_agent(messages, session_context)`.
5. `run_agent` calls the LLM with the system prompt + trimmed history + context. The LLM either replies or emits one or more tool calls.
6. Tool calls are forwarded over stdio to the FastMCP subprocess, which executes against Graph / DocuSign / Outlook / Teams clients.
7. The loop terminates on a tool-free reply (or `_MAX_TOOL_LOOPS`). The reply is sent back to Teams; the updated history is persisted.

### Power Automate new-hire submission → tracker + card
1. Power Automate posts to `POST /webhook/new-hire` with the shared secret.
2. `runtime/webhooks.handle_new_hire_webhook` validates the secret, parses the payload, enqueues a `QueueJob{kind: JOB_NEW_HIRE, payload: ...}`, and returns 202.
3. The queue worker pulls the job and calls `runtime/jobs.process_new_hire_job`.
4. That handler classifies the workflow (`new_hire` / `rehire` / `offboarding` / `temp`) via `domain/workflows.py` and `domain/*/policies.py`.
5. It calls `TrackerClient.upsert(...)` (Graph Excel), updates `CardStateStore`, builds the right adaptive card via `integrations/adaptive_cards.py`, and either sends a new card or updates the existing one via `integrations/teams/proactive.py`.
6. If the workflow allows it, it drafts the offer-letter envelope or queues the welcome email.

### DocuSign event → tracker update + card refresh
1. DocuSign Connect posts XML or JSON to `POST /webhook/docusign`.
2. `parse_docusign_payload` extracts envelope_id, status, and the custom identity fields embedded at envelope creation.
3. A `JOB_DOCUSIGN` job is enqueued.
4. `process_docusign_job` re-resolves the employee from the custom fields, updates the tracker stage, updates the DocuSign status card (or upgrades it to a "ready to add to roster" card when `completed`), and posts a Teams notification.

### Background-clearance webhook → confirmation
Similar to DocuSign: validate, enqueue, then `process_background_clearance_job` updates the tracker, posts a Teams notification, and sends the confirmation email from `templates/background_clearance_confirmation.html`.

## State boundaries

| What | Where | Lifetime |
|---|---|---|
| Workflow / card state per employee | Cosmos `state-records` via `state_store_cosmos.CosmosStateStore` | Long-lived |
| Teams thread session context | Cosmos `conversation-sessions` | Long-lived |
| In-flight jobs | Azure Storage Queue | Until acked by `process_job` |
| Agent chat history | Inside the conversation-session record | Trimmed each turn |
| Tracker / roster / separations | Excel via Graph | System of record |
| DocuSign envelopes | DocuSign | System of record |
| Anything else | (intentionally not persisted) | — |

There is no application database beyond Cosmos for runtime state. The "real" data lives in Excel and DocuSign.

## Configuration surfaces

- `.env` (local) / Container App env (deployed) — loaded by `config.py`.
- `config/staff_rosters.json` (local, gitignored) — the per-location workbook map. `scripts/sync_staff_rosters_to_tfvars.sh` syncs it into Terraform tfvars before deploy.
- `infra/terraform/foundation/` — shared platform: resource group, ACR, Container Apps environment, Log Analytics, Storage, Cosmos, Key Vault, user-assigned identity, Azure OpenAI, Bot.
- `infra/terraform/app/` — the Container App itself, app-specific Cosmos containers, the storage queue.
- `teamsappPackage.example/` — commit-safe Teams sideload template; the real `teamsappPackage/` is local-only.

## Extension points

When adding new behavior, prefer the smallest extension point that fits:

1. **New agent capability** — add a `@mcp.tool()` in `mcp_server/tools_*.py`. The LangChain runner discovers it automatically; no changes to the runner or runtime.
2. **New webhook trigger** — add a route in `server.py`, a handler in `runtime/webhooks.py`, a job kind in `runtime/jobs.py`, and (usually) a card in `integrations/adaptive_cards.py`.
3. **New external system** — add a client under `integrations/<system>/`, surface it through MCP tools, and import it from `runtime/jobs.py` only if it's part of the deterministic webhook path.
4. **New workflow type** — add it to `domain/workflows.py` and a `domain/<type>/policies.py` module. The runtime branches in `process_new_hire_job` consult those policies.

Avoid putting business logic directly in `server.py`, in webhook handlers, or in `integrations/` clients — those layers should stay thin.

## Where this doc stops

This walkthrough covers the steady-state architecture. For operational topics (deploys, rollbacks, smoke tests, CI) see `RUNBOOK.md` at the repo root. For an interactive, click-through version of the same module graph, open `docs/walkthrough/react-architecture-explorer/`.
