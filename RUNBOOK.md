# Runbook

This document is the operator-focused companion to `ARCHITECTURE.md`.

It answers:

- how to deploy the app
- how to validate a release
- how to rollback
- what to monitor
- how to test changes safely once the app is in regular use

It is intentionally practical rather than exhaustive.


## What Is Running

The production deployment is one Azure Container App running:

- the aiohttp web app
- the Teams bot endpoint
- the webhook endpoints
- the in-process queue worker
- the FastMCP subprocess for tools

Durable external services:

- Cosmos DB
  - state store container for business/UI state
  - conversation-session container for Teams memory/session state
- Azure Queue Storage
  - onboarding job queue
- Azure Container Registry
- Log Analytics


## Current Runtime Model

The system uses a mixed execution model:

- deterministic runtime for webhooks and adaptive-card button actions
- LangChain agent for interactive Teams queries

Operational consequences:

- new-hire, DocuSign, and background-clearance webhook flows should not depend
  on LLM tool orchestration
- card buttons such as send-email and send-offer-letter should behave
  deterministically
- Teams query behavior still depends on prompt + tool quality


## State and Retention

Current retention model:

- `conversation_ref`
  - indefinite
  - required for proactive posting back into the Teams channel

- channel thread/session memory
  - 7-day lifecycle

- `thread_seed_context`
  - 30-day TTL
  - used to rehydrate expired channel threads when users reply to an older post

- adaptive card state
  - 30-day TTL
  - includes `new_hire_card` and `docusign_card`

TTL is implemented by the application at write time through the state-store
layer, not by Terraform.


## Environments

### Recommended long-term shape

Once the main app is in active daily use, new feature testing should happen in
a separate deployed environment.

Recommended setup:

- `dev` environment
- `prod` environment

With environment-specific variables such as:

- `terraform.dev.tfvars`
- `terraform.prod.tfvars`

Use one Terraform configuration, not separate `main.tf` files.

### Why this matters

Testing new features directly in the live production app is risky because this
system has shared operational state:

- webhook queues
- Cosmos state
- Teams proactive cards and reply threads
- Excel tracker and staff roster writes

Separate environments reduce:

- accidental production state mutation
- queue pollution
- false HR notifications
- adaptive-card collisions
- ambiguity when debugging live issues

### Minimum dev/prod separation

The safer baseline is:

- separate Container App
- separate queue
- separate webhook base URL and secret
- separate Teams test channel
- separate Cosmos database/containers or clearly separated namespaces

Prefer separate downstream non-prod integrations as well where possible:

- DocuSign sandbox
- non-prod test workbook
- non-prod email/test recipients


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
scripts/build_and_push_container_app.sh
```

Manual fallback:

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

That seeds the durable channel conversation reference in Cosmos.


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

### Channel thread continuity

1. Trigger a proactive/adaptive-card post in the channel
2. Reply under that post
3. Ask a follow-up that relies on seeded context

Expected:

- the reply thread reuses the employee/workflow context from the root post
- channel memory is thread-scoped, not channel-scoped

### New-hire flow

Trigger one Power Automate submission.

Expected:

1. webhook returns `200`
2. employee is added to tracker
3. DocuSign draft exists
4. onboarding email draft exists
5. Teams submission card posts

### Card buttons

Click:

- `Send Welcome Email`
- `Send Offer Letter`

Expected:

- action succeeds
- original card updates
- no duplicate-send state
- tracker/card state reflects the deterministic action

### Background clearance flow

Trigger one background-clearance submission.

Expected:

1. webhook returns `200`
2. tracker updates `Background Submission`
3. Teams background-clearance notification posts
4. confirmation email sends or fails without poisoning the queue


## Common Operational Issues

### 1. Container App starts but does not answer

Check:

```bash
az containerapp revision list --resource-group OnboardingAgent --name onboarding-agent --output table
az containerapp logs show --resource-group OnboardingAgent --name onboarding-agent --tail 200
```

Typical causes:

- bad secret/env-var value
- Teams/Graph credential issue
- startup failure in queue or Cosmos initialization

### 2. Channel proactive posts fail

Check:

- bot endpoint is correct
- app is installed in the target team/channel
- at least one real inbound channel activity has occurred since install

Remember:

- proactive posting depends on a stored channel conversation reference
- that reference is intentionally long-lived

### 3. Repeated background-clearance notifications

Likely causes:

- poisoned queue message being retried
- downstream confirmation-email failure after Teams notification

Current behavior:

- queue messages over the retry threshold are deleted
- background-clearance email failure should not keep re-poisoning the message

### 4. Card actions update the wrong employee/workflow

Check:

- card payload includes `employee_email`, `work_location`, `job_title`,
  and `status_change`
- tracker row identity is unique on the composite identity
- DocuSign draft was created with current custom-field metadata

### 5. Old channel thread reply has no context

Check:

- reply is actually under the original post
- thread seed context has not expired yet
- card state or seed context still exists in Cosmos

Current behavior:

- thread memory expires after 7 days
- thread seed context persists for 30 days and should rehydrate the thread


## Rollback

Use an older image tag that is already in ACR and re-apply Terraform with that
tag.

Typical rollback flow:

1. set `image_tag` in the chosen tfvars file to the prior known-good tag
2. run:

```bash
scripts/deploy_container_app.sh infra/terraform/container-app/terraform.tfvars apply
```

Rollback should not require rebuilding an image if the prior tag still exists
in ACR.


## Operational Direction

Current recommended direction:

- keep production workflow execution deterministic
- keep the LLM focused on interactive Teams queries
- use a separate deployed dev environment for feature validation
- keep retention explicit for every durable state category except the channel
  conversation reference needed for proactive posting
