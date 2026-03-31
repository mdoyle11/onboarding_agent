# Runbook

This document is the operator-focused companion to `ARCHITECTURE.md`.

It answers:

- how to deploy the app
- how to validate a release
- how to rollback
- what to monitor
- how CI/CD should evolve as the agent changes

It is intentionally practical rather than exhaustive.

## What Is Running

The production deployment is one Azure Container App running:

- the aiohttp web app
- the Teams bot endpoint
- the webhook endpoints
- the in-process Azure Queue worker
- the FastMCP subprocess for tools

Durable external services:

- Cosmos DB
  - `state-records`
  - `conversation-sessions`
- Azure Queue Storage
  - `onboarding-jobs`
- Azure Container Registry
- Log Analytics

## Environments

Current expectation:

- one shared Azure resource group
- one shared Cosmos account
- one shared Storage account
- one shared ACR
- one app-specific Container App deployment

Terraform only manages the app-specific layer and child resources.

## Deployment Inputs

The deployable config lives in:

- `infra/terraform/container-app/terraform.tfvars`

Use:

- `infra/terraform/container-app/terraform.tfvars.example`

to see what must be provided.

Important categories:

- Azure app credentials
- Teams bot credentials
- Excel tracker IDs
- DocuSign credentials
- queue connection string
- Cosmos key
- webhook secret
- image tag

Sensitive local-only files:

- `.env`
- `config/staff_rosters.json`
- `teamsappPackage/`
- `terraform.tfvars`

## Deployment Workflow

### 1. Sync staff roster config if needed

If you are using a local `config/staff_rosters.json`, sync it into
`terraform.tfvars` before deploy:

```bash
scripts/sync_staff_rosters_to_tfvars.sh infra/terraform/container-app/terraform.tfvars
```

### 2. Build and push the image

Default helper:

```bash
scripts/build_and_push_container_app.sh <acr-name> <image-tag>
```

If `az acr login` is flaky, manual fallback:

```bash
docker build --progress=plain -t <acr-login-server>/onboarding-agent:<image-tag> .
docker push <acr-login-server>/onboarding-agent:<image-tag>
```

### 3. Update the image tag

Edit:

- `infra/terraform/container-app/terraform.tfvars`

Set:

```hcl
image_tag = "YYYY-MM-DD-N"
```

Use immutable tags. Do not rely on `latest`.

### 4. Plan and apply Terraform

```bash
scripts/deploy_container_app.sh infra/terraform/container-app/terraform.tfvars plan
scripts/deploy_container_app.sh infra/terraform/container-app/terraform.tfvars apply
```

If Azure refresh is flaky:

```bash
cd infra/terraform/container-app
terraform plan -refresh=false -var-file=terraform.tfvars
terraform apply -refresh=false -var-file=terraform.tfvars
```

### 5. Read outputs

```bash
cd infra/terraform/container-app
terraform output
```

Important outputs:

- `container_app_fqdn`
- `container_app_url`
- `teams_bot_endpoint`
- `webhook_base_url`

## Teams Setup

### Bot endpoint

Set the Azure Bot / bot registration messaging endpoint to:

```text
https://<container_app_fqdn>/api/messages
```

### Teams sideload package

The real local package is:

- `teamsappPackage/`

The commit-safe template is:

- `teamsappPackage.example/`

To build the real package for the current host:

```bash
scripts/package_teams_app.sh <container_app_fqdn>
```

Then upload the generated zip in Teams and install or update the app in the
target team/chat.

After installation:

1. Send one real message in the target channel
2. Mention the bot once

That seeds the conversation reference in Cosmos.

## Smoke Test Checklist

Run these after each deploy.

### Infrastructure health

1. Container App revision is active
2. Container App revision is not crash-looping
3. `/api/messages` responds

Useful commands:

```bash
az containerapp revision list --resource-group OnboardingAgent --name onboarding-agent --output table
az containerapp logs show --resource-group OnboardingAgent --name onboarding-agent --tail 200
curl --max-time 10 https://<container_app_fqdn>/api/messages
```

### Teams

1. DM the bot
2. Mention the bot in the configured channel
3. Ask for status of a known employee

Expected:

- DM response works
- channel mention works
- status summary includes tracker stages and DocuSign status

### New-hire flow

Trigger one Power Automate submission.

Expected:

1. webhook returns `200`
2. employee is added to tracker
3. DocuSign draft exists
4. onboarding email draft exists
5. Teams new-hire card posts

### Card buttons

Click:

- `Send Welcome Email`
- `Send Offer Letter`

Expected:

- action succeeds
- original card updates
- no duplicate send state

### Background clearance flow

Trigger one background-clearance submission.

Expected:

1. webhook returns `200`
2. tracker attempts `Background Submission`
3. Teams background-clearance notification posts
4. confirmation email sends

## Common Operational Issues

### 1. Container App starts but does not answer

Check:

```bash
az containerapp revision list --resource-group OnboardingAgent --name onboarding-agent --output table
az containerapp logs show --resource-group OnboardingAgent --name onboarding-agent --tail 200
```

Typical causes:

- bad startup config
- missing env vars in the MCP subprocess
- session-store misconfiguration
- queue startup failure

### 2. Teams bot does not respond

Check:

- bot messaging endpoint
- Teams app package host
- manifest bot ID
- current container logs

### 3. Webhooks reach the app but the flow hangs

If the server logs show:

```text
POST /webhook/... HTTP/1.1" 200
```

then the app is not the thing keeping the Power Automate run open.

Use the regular `HTTP` action in Power Automate, not the webhook-style action.

### 4. Teams card actions say “something went wrong”

If backend logs show the tool succeeded, the common issue is client timeout on
the click path. The current implementation now acknowledges card actions
quickly and performs the actual work in the background.

### 5. Stale card state or wrong conversation behavior

Reset runtime state if needed:

```bash
.venv/bin/python scripts/reset_runtime_state.py \
  --cosmos-endpoint "<endpoint>" \
  --cosmos-key "<key>" \
  --database "onboarding-agent" \
  --container "state-records" \
  --employee-email "user@example.com" \
  --all-conversation-refs
```

Then reseed the channel by sending a new message to the bot.

### 6. ACR login is flaky

If `az acr login` hangs or times out but direct registry access works, use
manual `docker login` and `docker push` as a fallback.

## Rollback

The simplest rollback is image-based.

1. Identify the last good image tag
2. Put that tag back into `terraform.tfvars`
3. Apply Terraform again

Because the state lives outside the container, rollback is normally low-risk.

Rollback command sequence:

```bash
scripts/deploy_container_app.sh infra/terraform/container-app/terraform.tfvars apply
```

after restoring the prior `image_tag`.

## Logs and Diagnostics

Primary production diagnostics:

```bash
az containerapp logs show --resource-group OnboardingAgent --name onboarding-agent --tail 200
az containerapp revision list --resource-group OnboardingAgent --name onboarding-agent --output table
```

Important log families:

- aiohttp access logs
- Teams bot logs
- queue job logs
- Graph request timing logs
- DocuSign client logs

Useful patterns:

- `Processed queued new-hire job`
- `Processed queued background-clearance job`
- `Tool ... result=`
- `Updated new-hire card`
- `Graph invocation failed`
- `Application startup failed`

## Data and Retention

### State records

`state-records` contains:

- conversation references
- card state
- other application-level durable state

This is business/UI state and should remain durable.

### Conversation sessions

`conversation-sessions` stores ephemeral Teams session metadata and chat
history continuity.

This data is intentionally short-lived and should use TTL so conversational
memory does not grow without bound.

Current guidance:

- keep this data separate from durable application state
- use TTL to expire stale sessions automatically

## CI/CD Considerations

This project can be deployed manually today, but if you want to keep improving
the agent safely, CI/CD needs to protect two different concerns:

1. normal application correctness
2. agent behavior drift

Those are not the same problem.

### Recommended pipeline stages

#### Stage 1: Static validation

Run on every PR:

- Python syntax validation
- dependency install
- unit tests
- Terraform formatting
- shell script linting if added later

Minimum useful checks:

```bash
uv sync
python3 -m py_compile src/onboarding_agent/**/*.py
uv run python -m pytest tests/unit -q
terraform fmt -check infra/terraform/container-app
```

#### Stage 2: Build validation

Run on every PR that changes runtime or deployment code:

- Docker build
- package install inside image

This catches:

- broken Docker context
- missing files
- wrong template paths
- missing runtime dependencies

#### Stage 3: Non-prod deploy

On merge to a deployment branch:

- build image
- push immutable tag
- deploy to a non-prod Container App

Use the same Terraform module with different tfvars.

#### Stage 4: Smoke tests

Run lightweight hosted checks after deploy:

- `/api/messages` probe
- Teams bot DM
- one synthetic webhook
- one status query

This is the first stage that actually validates the hosted integration chain.

### What CI can verify well

CI is good at validating:

- syntax
- imports
- unit logic
- Docker build integrity
- Terraform validity
- scripted deployment steps

### What CI cannot verify well by itself

CI cannot fully guarantee:

- LLM chooses the ideal tools every time
- Teams client behavior is perfect
- Graph workbook schemas remain stable
- DocuSign callbacks are behaving correctly
- Power Automate semantics remain unchanged

That means CI/CD must be paired with targeted operational smoke tests.

## Continuous Improvement Strategy For The Agent

The safest way to improve this system is to separate changes into three buckets.

### 1. Deterministic platform changes

Examples:

- queue handling
- webhook auth
- Cosmos storage
- deployment scripts
- Terraform

These should be improved aggressively because they do not depend on model
judgment.

### 2. Agent behavior changes

Examples:

- system prompt changes
- tool descriptions
- tool naming
- status summarization behavior

These need regression awareness, because small prompt changes can alter tool
selection in surprising ways.

Recommended practice:

- keep prompt changes small
- test them against a fixed set of representative onboarding scenarios
- document why the prompt changed

### 3. Critical side effects

Examples:

- tracker row creation
- stage updates
- card state updates
- webhook acknowledgment

These are the places where pure agentic behavior should be treated carefully.
Not everything needs to be deterministic, but correctness-critical writes should
not be left ambiguous if they repeatedly prove flaky.

### Practical rule for future work

When adding a new step or tool, ask:

1. Is this step optional or judgment-heavy?
   If yes, it can stay agent-driven.

2. Is this step the system-of-record write that defines success?
   If yes, it may eventually deserve deterministic orchestration.

This prevents overcorrecting into a rigid workflow engine while still keeping
the backbone reliable.

## Suggested Future CI/CD Improvements

When the manual workflow becomes repetitive, add these in order:

1. GitHub Actions for unit tests and Docker build
2. Automatic image tagging from commit SHA
3. Staging deploy workflow
4. Post-deploy smoke test job
5. Optional production promotion workflow

Do not start with a fully automated production release pipeline. The repo is
still evolving quickly enough that manual approval and inspection remain useful.

## Summary

The current operating model is:

- one hosted Container App
- durable ingress through Azure Queue
- durable app state in Cosmos
- LangChain agent runner + MCP for flexible agent behavior
- manual but workable deployment flow

That is a good base for continued iteration.

The next maturity step is not a rewrite. It is:

- lightweight CI
- repeatable staging deploys
- smoke tests around the highest-value workflows
- careful changes to prompts and critical side-effect paths
