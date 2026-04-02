# Architecture Guide

This document describes the current repository shape on the
`refactor/remove-langgraph` branch.

The project is now a single Azure Container App with a mixed architecture:

- deterministic workflow execution for business events
- a plain LangChain tool-calling agent for Teams queries
- Excel as the workflow source of truth
- Cosmos-backed app state for continuity, card state, and conversation metadata

LangGraph is no longer part of the runtime.

## Purpose

This system supports HR onboarding and employee-change workflows across:

- Microsoft Forms / Power Automate intake
- Teams conversations and adaptive-card actions
- Excel onboarding tracker updates
- staff roster updates
- DocuSign offer-letter drafting and status tracking
- background-clearance form handling

Current deterministic workflow families:

1. `New Hire`
2. `Promotion`
3. `Pay Increase`
4. `Transfer In`
5. `Rehire`

Termination is intentionally deferred for a later dedicated workflow/persona.

## Core Principle

Business workflow execution is deterministic.

The LLM is used for:

- interpreting Teams user requests
- deciding which high-level tool to call
- summarizing tool results back to HR

The LLM is not responsible for:

- webhook routing
- stage progression logic
- offer-letter lifecycle transitions
- tracker writes for workflow automation

## High-Level Runtime Shape

The app is one deployable service with four internal layers:

1. HTTP and bot entrypoints
   - `src/onboarding_agent/server.py`

2. Runtime orchestration
   - `src/onboarding_agent/runtime/`
   - `src/onboarding_agent/domains/onboard/`

3. Agent and MCP tool surface
   - `src/onboarding_agent/agent/`
   - `src/onboarding_agent/mcp_server/`

4. External integrations
   - `src/onboarding_agent/integrations/`

There is also a small cross-domain business-primitive layer:

- `src/onboarding_agent/domain/`
  - shared identity and formatting helpers used across workflow domains

## Request Flow

### Teams Query Flow

1. Teams activity hits `POST /api/messages`
2. Teams bot logic classifies the activity:
   - normal Teams query
   - adaptive-card action
   - mention/reply handling
3. For normal queries, the app runs the LangChain agent loop
4. The agent calls MCP tools as needed
5. The app sends a Teams reply or updates a card

This is the only LLM-driven path.

### Adaptive Card Action Flow

1. User clicks a Teams card button
2. Button payload includes workflow identity fields
   - `employee_email`
   - `work_location`
   - `job_title`
   - `status_change`
3. The app resolves the correct stored card state
4. Deterministic action handling updates tracker/card state

### Webhook Flow

Endpoints:

- `POST /webhook/new-hire`
- `POST /webhook/docusign`
- `POST /webhook/background-clearance`

Flow:

1. Validate shared secret or parse payload
2. Normalize payload
3. Enqueue durable job
4. Return immediately
5. Background worker executes deterministic handler

Webhook handlers do not invoke the LLM.

## Workflow Runtime

The runtime layer owns durable orchestration concerns:

- `runtime/webhooks.py`
  - webhook auth, parsing, queue handoff

- `runtime/job_queue.py`
  - local and Azure queue implementations

- `runtime/jobs.py`
  - deterministic workflow executors
  - new-hire submission routing
  - DocuSign event handling
  - background-clearance handling

- `domains/onboard/policies.py`
  - centralized workflow stage exclusion policies

Current stage policies are applied by workflow type, for example:

- `Promotion` marks several onboarding-only stages `N/A`
- `Pay Increase` omits more onboarding-specific stages
- `Rehire` still receives offer-letter handling and welcome-email drafting

## State Ownership

There are three kinds of state:

1. Excel tracker state
   - business workflow truth
   - stage progression
   - employee submission records

2. Cosmos/file-backed app state
   - Teams conversation refs
   - adaptive card state
   - short-lived Teams chat/session memory

3. External system state
   - DocuSign envelopes
   - Outlook email delivery

The app deliberately avoids duplicating workflow state in an internal graph.

## Identity Model

The repository now uses a composite business identity where available:

- `email + work_location + job_title + status_change`

This identity is used across:

- tracker lookups
- tracker stage updates
- adaptive card state keys
- adaptive card action payloads
- DocuSign custom fields and webhook resolution

Email-only lookup is still allowed for interactive Teams queries, but it is a
fallback path. If multiple rows share the email, the system returns
disambiguation options instead of guessing.

## Agent Layer

The agent lives in `src/onboarding_agent/agent/runner.py`.

It is a plain async tool loop:

1. build prompt and compact session context
2. invoke model
3. execute tool calls
4. feed tool results back
5. stop when no more tool calls remain

The system prompt is intentionally narrow:

- use tools for tracker, roster, email, Teams, and DocuSign data
- ask short clarification questions when identity or required inputs are missing
- do not orchestrate webhook workflows

Session context now persists compact business identifiers such as:

- `employee_email`
- `employee_name`
- `work_location`
- `job_title`
- `status_change`
- `intent`

## MCP Tool Surface

The FastMCP server is launched as a subprocess over stdio.

Tool groups:

- `tools_tracker.py`
  - tracker lookup, stage updates, listing/filtering

- `tools_staff_roster.py`
  - roster capacity and deterministic roster updates

- `tools_docusign.py`
  - draft lookup, envelope creation, sending, status retrieval

- `tools_email.py`
  - welcome-email drafting/sending
  - background-clearance confirmation email

- `tools_onboarding.py`
  - composite onboarding status across tracker and DocuSign

- `tools_teams.py`
  - Teams notification/card helpers

The agent should prefer these higher-level tools instead of reasoning about raw
Excel or DocuSign primitives itself.

## Integration Layer

Key integration modules:

- `integrations/graph/`
  - Graph auth and shared Microsoft Graph access helpers

- `integrations/workbook/`
  - workbook client behavior
  - tracker/staff-roster schema aliases
  - workbook row/header/stage helpers

- `integrations/graph_workbook.py`
  - temporary compatibility shim re-exporting workbook helpers during refactor

- `integrations/workbook/tracker_client.py`
  - tracker record identity, writes, stage updates, listing

- `integrations/workbook/staff_roster_client.py`
  - staff-roster capacity and add flows

- `integrations/docusign_client.py`
  - draft creation, envelope sending, composite-aware envelope lookup

- `integrations/outlook_email_client.py`
  - email send operations

- `integrations/teams/`
  - Teams runtime, proactive messaging, card actions, replies

## Domain Primitives

Shared business primitives are separated from both integrations and
workflow-specific domains:

- `domain/identity.py`
  - composite identity normalization and key generation

- `domain/formatting.py`
  - shared display/date formatting logic

Workflow-specific policy and orchestration still live in:

- `domains/onboard/`

This keeps reusable business rules out of `integrations/` while avoiding
premature onboarding-specific placement for logic that will later be shared
with offboarding workflows.

## Deployment Shape

In Azure, the app currently runs as one Container App that hosts:

- aiohttp server
- Teams bot endpoint
- webhook endpoints
- queue worker
- MCP subprocess

Durable dependencies:

- Azure Queue Storage
- Cosmos DB
- Azure Container Registry
- Log Analytics

This monolith deployment is intentional for now. Internal domain boundaries are
being cleaned up first; service extraction can happen later if roster/Excel
scope justifies it.

## Current Tradeoffs

1. One container means shared scaling for web, queue, and MCP subprocess work
2. Excel remains the workflow source of truth, so Graph latency is significant
3. Some interactive DocuSign/status questions still depend on envelope
   discovery quality, so composite-aware envelope matching remains an important
   area of improvement

## Near-Term Direction

1. Continue hardening composite-aware DocuSign and status tooling
2. Keep business workflows deterministic
3. Build out roster domain abstractions as staff-roster CRUD expands
4. Revisit infra split later using `infra/FUTURE_INFRA.md`
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
