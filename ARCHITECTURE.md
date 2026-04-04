# Architecture Guide

This document describes the current runtime shape on the
`refactor/remove-langgraph` branch.

The application is a single Azure Container App with a mixed execution model:

- deterministic workflow execution for operational paths
- a plain LangChain tool-calling agent for interactive Teams queries
- Excel as the operational workflow record
- Cosmos-backed app state for Teams continuity, card state, and durable references

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
- tracker writes for automated workflow handling
- adaptive-card button execution
- DocuSign or background-clearance webhook state transitions


## High-Level Runtime Shape

The app is one deployable service with five internal layers:

1. HTTP and bot entrypoints
   - `src/onboarding_agent/server.py`

2. Runtime orchestration
   - `src/onboarding_agent/runtime/`
   - `src/onboarding_agent/domains/onboard/`

3. Agent and session-context handling
   - `src/onboarding_agent/agent/`

4. MCP tool surface
   - `src/onboarding_agent/mcp_server/`

5. External integrations
   - `src/onboarding_agent/integrations/`

There is also a cross-domain business-primitive layer:

- `src/onboarding_agent/domain/`
  - shared identity and formatting helpers used across workflow domains


## Request Flow

### Teams Query Flow

1. Teams activity hits `POST /api/messages`
2. Teams bot logic classifies the activity:
   - normal Teams query
   - adaptive-card action
   - mention/reply handling
3. For normal queries, the app loads thread/session context and short chat history
4. The LangChain agent loop runs
5. The agent calls MCP tools as needed
6. The app sends a Teams reply

This is the primary LLM-driven path.

### Adaptive Card Action Flow

1. User clicks a Teams card button
2. Button payload includes workflow identity fields:
   - `employee_email`
   - `work_location`
   - `job_title`
   - `status_change`
3. The app resolves the matching stored card state
4. Deterministic action handling executes directly
5. Tracker/card state is updated and the card is refreshed

Supported button actions are intentionally deterministic.

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

- `runtime/payloads.py`
  - shared payload normalization helpers

- `runtime/job_queue.py`
  - local and Azure queue implementations
  - poison-message protection

- `runtime/jobs.py`
  - deterministic workflow executors
  - new-hire submission routing
  - DocuSign event handling
  - background-clearance handling

- `domains/onboard/policies.py`
  - centralized workflow stage exclusion policies

Current stage policies are applied by workflow type, for example:

- `Promotion` marks onboarding-only stages `N/A`
- `Pay Increase` omits more onboarding-specific stages
- `Rehire` still receives offer-letter handling and welcome-email drafting


## State Ownership

There are four kinds of state:

1. Excel tracker and roster state
   - business workflow truth
   - stage progression
   - employee submission records
   - roster capacity and membership

2. Cosmos/file-backed app state
   - Teams conversation refs
   - adaptive card state
   - Teams thread seed context
   - short-lived Teams chat/session memory

3. External system state
   - DocuSign envelopes
   - Outlook email delivery

4. Queue state
   - pending webhook/background jobs in local or Azure queue backend

The app deliberately avoids duplicating workflow state in an internal graph.


## Identity Model

The repository uses a composite business identity where available:

- `email + work_location + job_title + status_change`

For newer deterministic workflow paths, the system now also carries a stable
`submission_id` from the intake form and treats it as the preferred workflow
key whenever it is available.

This identity is used across:

- tracker lookups
- tracker stage updates
- adaptive card state keys
- adaptive card action payloads
- DocuSign custom fields and webhook resolution
- Teams session-context seeding for thread continuity

`submission_id` is now propagated through:

- tracker row creation and lookup
- Teams session context
- new-hire and DocuSign card state
- adaptive-card action payloads
- tracker-backed DocuSign draft creation and deletion
- DocuSign custom fields and status callbacks

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
- treat seeded Teams thread context as default input for follow-up requests
- rely on MCP tool descriptions as the source of truth for detailed tool capabilities

Shared session-context fields live in:

- `src/onboarding_agent/agent/session_context.py`

Key stored context fields include:

- `submission_id`
- `employee_email`
- `employee_name`
- `work_location`
- `job_title`
- `status_change`
- `job_category`
- `intent`
- `envelope_id`


## Teams Memory Model

Teams channel memory is thread-scoped, not channel-scoped.

Channel thread identity:

- `channel:<conversation_id>:thread:<root_message_id>`

Active session key:

- `teams:channel:<conversation_id>:thread:<root_message_id>:<session_id>`

Behavior:

- top-level proactive posts seed structured context for that root thread
- replies under that post reuse the same thread-scoped context
- channel thread sessions expire after 7 days
- if a reply arrives after expiry, the app creates a fresh session and
  rehydrates it from durable thread seed context

DMs continue to use conversation-scoped session behavior rather than
thread-scoped channel behavior.


## State Retention

Current retention model:

- `conversation_ref`
  - indefinite
  - needed for proactive channel posting

- channel thread/session memory
  - 7-day lifecycle

- `thread_seed_context`
  - 30-day Cosmos TTL
  - used to rehydrate expired channel threads

- adaptive card state
  - 30-day Cosmos TTL
  - namespaces:
    - `new_hire_card`
    - `docusign_card`

Per-record TTL is implemented in code through the state-store layer:

- `src/onboarding_agent/runtime/state_store.py`
- `src/onboarding_agent/runtime/state_store_cosmos.py`

Terraform provisions the Cosmos container, but the application sets document TTL
at write time.


## MCP Tool Surface

The FastMCP server is launched as a subprocess over stdio.

Tool groups:

- `tools_tracker.py`
  - tracker row lookup
  - tracker row create/update/delete
  - stage updates/clears
  - listing/filtering

- `tools_staff_roster.py`
  - roster capacity
  - row inspection
  - section-aware add/remove/update operations

- `tools_docusign.py`
  - draft lookup/list/delete
  - tracker-backed draft creation
  - envelope sending
  - status retrieval

- `tools_email.py`
  - welcome-email drafting/sending
  - background-clearance confirmation email

- `tools_onboarding.py`
  - composite onboarding status across tracker and DocuSign

- `tools_teams.py`
  - Teams notification/card helpers

Thin shared client factories live in:

- `src/onboarding_agent/mcp_server/clients.py`

Tool descriptions now carry most capability-specific guidance:

- tracker CRUD and stage semantics
- staff-roster CRUD/editable fields
- DocuSign sequencing expectations
- onboarding email draft/send behavior

This keeps the agent prompt shorter and reduces drift between prompt text and
tool implementation.


## Integration Layer

Key integration modules:

- `integrations/graph/`
  - Graph auth and shared Microsoft Graph access helpers

- `integrations/workbook/`
  - workbook client behavior
  - tracker/staff-roster schema aliases
  - workbook row/header/stage helpers
  - workbook-specific tracker and roster adapters
  - section-aware roster insertion/deletion above per-group `Totals` rows
  - tracker row-level CRUD for actual tracker data fields, not just stages

- `integrations/docusign_client.py`
  - draft creation, listing, and draft-only deletion
  - envelope sending
  - submission-id-aware envelope lookup and callback correlation

- `integrations/card_state.py`
  - durable adaptive card state
  - tracker-backed card refresh/rehydration
  - submission-id-aware card lookup for newer workflow paths

- `integrations/teams/`
  - bot handlers
  - proactive posting
  - memory/session handling
  - deterministic card action execution


## Operational Guidance

When adding new functionality:

1. Put workflow rules in deterministic runtime/domain code first
2. Add or extend high-level MCP tools only when interactive Teams behavior needs them
3. Keep workbook/Graph IO in `integrations/workbook` and `integrations/graph`
4. Keep shared business primitives in `domain/`
5. Avoid reintroducing email-only identity assumptions into operational paths
6. Keep prompt policy short; prefer tool docstrings for exact capability detail
7. Preserve the distinction between tracker `job_title` and roster `job_category`
8. Treat the tracker as the source of truth for downstream HR actions and card refreshes
9. Prefer `submission_id` over mutable business fields when a workflow already has it

The general direction remains:

- deterministic workflows for HR operations
- tool-assisted LangChain agent for Teams interaction
- bounded durable state with explicit retention
