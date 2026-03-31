# Architecture Guide

This document explains the current shape of the repository as it exists on the
`feature/container-app-deployment` branch. It covers the application from top
to bottom:

- what the system does
- how requests move through the agent
- how state is stored
- how Teams, Power Automate, Graph, Outlook, and DocuSign fit together
- how the project is packaged and deployed to Azure

The goal is not to describe every line of code. The goal is to make the repo
easy to reason about before you change it.

## Purpose

This project is an AI-assisted HR onboarding system built around a LangChain
tool-calling agent runner.

It handles three main kinds of work:

1. New-hire intake
   Power Automate posts a form submission. The system updates the onboarding
   tracker, prepares a DocuSign draft, prepares an onboarding email draft, and
   posts a Teams card for HR.

2. Ongoing onboarding actions
   HR can use Teams messages or Teams card buttons to send the welcome email,
   send the DocuSign offer letter, check status, and complete follow-up steps.

3. Webhook-driven status updates
   DocuSign status callbacks and background-clearance form submissions update
   the tracker and notify HR.

## High-Level Shape

At runtime, the application is still one deployable service, but internally it
has four distinct layers:

1. HTTP entrypoints
   `src/onboarding_agent/server.py`

2. Workflow runtime
   `src/onboarding_agent/runtime/`

3. Agent and tools
   `src/onboarding_agent/agent/`
   `src/onboarding_agent/mcp_server/`

4. External integrations
   `src/onboarding_agent/integrations/`

In Azure, this runs as a single Container App. The container receives Teams and
webhook traffic, stores durable state in Cosmos DB, and uses Azure Queue
Storage for durable webhook handoff.

## Request Flow

### Teams

Teams messages hit:

- `GET /api/messages` for health probing
- `POST /api/messages` for bot traffic

The handler is built in `server.py` using the Microsoft 365 Agents SDK.

Flow:

1. Teams sends an activity to `/api/messages`
2. The Agents SDK adapter hands the activity to
   `integrations/teams_bot.py`
3. The bot stores or refreshes the Teams conversation reference
4. The bot decides whether the message is:
   - a normal user query
   - a card action
   - a channel mention
5. The bot invokes the agent runner, or for card actions schedules the
   action in the background
6. The bot updates the relevant Teams card or sends a reply

### Webhooks

Webhook endpoints are:

- `POST /webhook/new-hire`
- `POST /webhook/docusign`
- `POST /webhook/background-clearance`

These handlers live in:

- `src/onboarding_agent/runtime/webhooks.py`

Flow:

1. Validate request format and shared secret
2. Parse the incoming payload
3. Enqueue a durable job
4. Return a small `200 OK` JSON response immediately

The HTTP layer does not run the full workflow inline. That was an intentional
change to avoid fire-and-forget `asyncio.create_task()` request handling in
production.

## Application Entrypoint

The main application entrypoint is:

- `src/onboarding_agent/server.py`

It is responsible for:

- building the aiohttp app
- wiring the Teams Agents SDK adapter
- creating the runtime state store
- initializing the agent runner
- starting the job queue worker
- registering webhook routes

Startup sequence:

1. Initialize state store
2. Initialize the agent runner
3. Initialize job queue
4. Start accepting traffic

Shutdown sequence:

1. Stop the queue worker

## Runtime Layer

The `runtime/` package exists to hold operational plumbing that should not be
mixed into the HTTP entrypoint or the agent definition.

Files:

- `runtime/webhooks.py`
  Webhook parsing, auth checks, and queue handoff

- `runtime/job_queue.py`
  Queue abstraction with:
  - `LocalJobQueue` for local development
  - `AzureStorageJobQueue` for Azure

- `runtime/jobs.py`
  Concrete queued job handlers for:
  - new hire
  - DocuSign
  - background clearance

- `runtime/state_store.py`
  State store abstraction with file-backed and Cosmos-backed variants

- `runtime/state_store_cosmos.py`
  Cosmos implementation for state records

This package is where deployment-oriented concerns live: durability, queueing,
and runtime state.

## Agent Layer

The agent lives in:

- `src/onboarding_agent/agent/runner.py`
- `src/onboarding_agent/agent/chat_history.py`

### Runner

The runtime is a plain async agent loop:

1. Ask the model what to do
2. Execute tool calls
3. Feed tool results back to the model
4. Continue until no more tool calls remain

The runner also:

- prepends the system prompt
- trims Teams message history before invocation
- retries model failures up to a bounded limit
- caps tool-loop iterations for safety

### Chat History

`agent/chat_history.py` persists short-lived Teams conversation history through
the existing state-store abstraction.

That history is:

- keyed by rotating Teams session keys
- stored separately from durable business state
- stripped of system messages before persistence
- used for conversational continuity, not workflow state

### System Prompt

The main system prompt is in `agent/runner.py`.

It defines:

- which onboarding stages exist
- how webhook-triggered runs should behave
- how Teams query runs should behave
- how to use the tracker, DocuSign, and email tools

The agent remains useful because it handles judgment-heavy flows well, but the
project now uses deterministic orchestration for some reliability-critical
pieces such as durable webhook ingestion.

## MCP Tool Server

The tool layer lives in:

- `src/onboarding_agent/mcp_server/server.py`
- `src/onboarding_agent/mcp_server/tools_*.py`

The FastMCP server is launched as a subprocess over stdio by the agent
runner.

This means the current architecture is:

- main aiohttp app process
- spawned FastMCP subprocess
- stdio transport between them

The MCP server registers four tool groups:

- `tools_graph.py`
  Excel tracker operations, Teams notifications, staff roster updates

- `tools_docusign.py`
  Draft/send/check DocuSign envelopes

- `tools_email.py`
  Draft/send onboarding email and background-clearance confirmation email

- `tools_onboarding.py`
  Composite status lookup across tracker and DocuSign

The MCP subprocess initializes the same runtime state store as the parent app,
because some tools need shared persisted state such as Teams card state.

## External Integrations

The `integrations/` package contains the actual clients and Teams-specific UX
logic.

### Microsoft Graph

- `integrations/graph_client.py`

This is the Excel tracker client and also the Teams notification helper.

It handles:

- onboarding tracker row lookup
- onboarding tracker row creation
- stage updates
- listing employees
- staff roster capacity checks
- staff roster writes
- Teams notification sending

The onboarding tracker is an Excel workbook accessed through Microsoft Graph.
That workbook is the operational source of truth for stage progression.

### Outlook

- `integrations/outlook_email_client.py`

Used by `tools_email.py` to send real emails through Microsoft Graph.

### DocuSign

- `integrations/docusign_client.py`

Handles:

- envelope draft creation
- send operations
- status lookup
- DocuSign Connect callback support

### Teams Bot Logic

- `integrations/teams_bot.py`

This is the main conversational/controller layer for Teams.

It handles:

- mention detection
- card action parsing
- card action completion checks
- replying to user messages
- background execution for card actions
- Teams card updates after successful actions

### Teams Proactive Messaging

- `integrations/teams_proactive.py`

This stores conversation references and sends proactive messages back into
Teams.

This is what allows webhook-driven workflows to create or update cards in a
channel after the original webhook request has already returned.

### Adaptive Cards

- `integrations/adaptive_cards.py`

Defines the card payloads for:

- new hire notifications
- DocuSign status updates
- background-clearance notifications
- generic notifications

### Persistent Card State

- `integrations/card_state.py`

Stores persisted metadata for cards, such as:

- Teams message ID
- employee email
- whether the welcome email has been sent
- whether the offer letter has been sent
- DocuSign card state

This is required so button clicks can update the original card rather than
posting duplicate follow-ups.

## State and Persistence

There are two distinct persistence types in the system.

### 1. Application state

Stored in the `state-records` Cosmos container through:

- `runtime/state_store.py`
- `runtime/state_store_cosmos.py`

This includes:

- Teams conversation references
- persisted new-hire card state
- persisted DocuSign card state

This data is business-important and intentionally durable.

### 2. Conversation sessions

Stored in the `conversation-sessions` Cosmos container through:

- `runtime/state_store.py`
- `agent/chat_history.py`
- `integrations/teams_session.py`

This data is ephemeral conversational memory:

- rotating Teams session metadata
- persisted chat history for short follow-up continuity

Important distinction:

- `state-records` stores durable business/UI state
- `conversation-sessions` stores short-lived conversational state

These are different containers because they have different operational value and
retention needs.

## Queueing and Background Work

The queue design is intentionally minimal.

The interface is:

- `JobQueue.start()`
- `JobQueue.enqueue()`
- `JobQueue.close()`

Implementations:

- `LocalJobQueue`
  Schedules jobs in-process for local development

- `AzureStorageJobQueue`
  Writes jobs to Azure Queue Storage and runs a simple in-container polling
  worker

This keeps local development simple while making production webhook handling
durable.

### Current queued jobs

- `new_hire_webhook`
- `docusign_webhook`
- `background_clearance_webhook`

### Job handling strategy

Not all jobs are handled the same way:

- new-hire and DocuSign still primarily use the agent runner
- background-clearance is now handled more deterministically in
  `runtime/jobs.py`

That split is intentional. Judgment-heavy and flexible paths stay agentic;
small reliability-critical flows can be made more explicit when needed.

## Configuration

Configuration lives in:

- `src/onboarding_agent/config.py`

It uses `pydantic-settings` and supports:

- `.env` for local development
- Container App env vars and secrets for Azure

Major config groups:

- LLM provider
- Teams / Agents SDK
- Microsoft Graph
- staff roster workbook map
- DocuSign
- Outlook sender
- webhook secret
- state store backend
- job queue backend

The same settings model is used by:

- the main aiohttp app
- the MCP subprocess
- local scripts

## Repository Layout

Top-level areas:

- `src/onboarding_agent/`
  Main Python package

- `templates/`
  HTML email templates

- `config/`
  Local-only or example config files

- `scripts/`
  Operational helpers for:
  - build/push
  - deploy
  - Teams package generation
  - staff roster JSON syncing
  - state reset

- `infra/terraform/container-app/`
  Azure infrastructure definition

- `teamsappPackage.example/`
  Commit-safe example of the Teams sideload package

- `tests/unit/`
  Unit tests for queueing, jobs, and webhook parsing

## Deployment Strategy

The current production strategy is intentionally conservative:

- keep the aiohttp app intact
- package it as one container
- run it in one Azure Container App
- use external managed services for durability

That means:

- HTTP ingress is handled by the Container App
- Teams and webhook routes are in the same process
- the queue worker runs inside the same container
- the MCP server runs as a subprocess inside the same container

This is not the most decomposed architecture possible. It is the smallest
architecture that gives durable ingress and hosted operation without
re-architecting the whole repo.

## Azure Infrastructure

Terraform lives in:

- `infra/terraform/container-app/`

The current module is designed to reuse shared Azure foundation resources:

- existing resource group
- existing ACR
- existing Cosmos account
- existing Storage account

Terraform manages the app-specific layer:

- Log Analytics workspace
- Azure Queue Storage queue
- Cosmos SQL database
- Cosmos SQL container for app state
- Cosmos SQL container for Teams conversation sessions
- Container Apps environment
- Container App

This keeps `terraform destroy` scoped to the app layer if the shared resources
are kept as data sources rather than managed top-level resources.

## Container and Runtime Packaging

Files:

- `Dockerfile`
- `.dockerignore`

The container runs:

- `python -m onboarding_agent.server`

The image includes:

- application code
- templates

It does not depend on committing sensitive local config such as the real staff
roster mapping or the real Teams app package.

## Teams App Packaging

The real Teams sideload package is intentionally local-only:

- `teamsappPackage/` is ignored

A commit-safe template is included:

- `teamsappPackage.example/`

The helper script:

- `scripts/package_teams_app.sh`

rewrites the manifest host and rebuilds a sideload zip for the current deployed
Container App host.

## Local Development

Local development is still straightforward:

1. `uv sync`
2. configure `.env`
3. run:
   - `uv run python -m onboarding_agent.server`

In local mode you typically use:

- file-backed state store
- local in-process queue
- stdio MCP subprocess

That keeps the repo easy to run without Azure.

## Operational Notes

### Why some things are durable and some are not

The current design draws the line here:

- durable:
  webhook handoff, card state, conversation references

- not independently durable:
  individual in-memory request handling inside one running container

That is an acceptable tradeoff for this stage of the system.

### Why the app can feel slow

The system does a lot of network-bound work:

- LLM calls
- Graph calls
- DocuSign calls
- Teams proactive sends
- Cosmos reads/writes

So latency is mostly external I/O and orchestration overhead, not just container
CPU.

### Why conversation memory stays bounded

Teams conversational context is intentionally kept short-lived. Session rotation,
TTL-backed persistence, and message trimming keep conversational memory from
growing without bound while leaving durable workflow state in external systems.

## Current Architectural Direction

The repo is now in a pragmatic middle state:

- more durable than the original local-only monolith
- still simple enough to understand as one service
- modular enough that future extraction is possible

If the system grows further, the most likely future splits would be:

- separate queue worker from the web container
- separate MCP server into its own hosted service
- make more critical side effects deterministic where reliability demands it

For now, the architecture is intentionally optimized for:

- shipping
- operability
- minimal infrastructure surface area
- preserving the existing codebase rather than rewriting it
