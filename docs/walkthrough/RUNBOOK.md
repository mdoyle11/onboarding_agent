# Runbook

Operational guide for the onboarding agent. Pairs with `ARCHITECTURE.md`.

The goal is full handover: someone who has never touched this project should be able to bring up a working environment from scratch, deploy it, observe it, and recover from common problems by following this document end-to-end.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [One-time external setup](#2-one-time-external-setup)
3. [Local development](#3-local-development)
4. [Configuration reference](#4-configuration-reference)
5. [Infrastructure (Terraform)](#5-infrastructure-terraform)
6. [Build and deploy](#6-build-and-deploy)
7. [Teams app packaging and sideload](#7-teams-app-packaging-and-sideload)
8. [Smoke tests](#8-smoke-tests)
9. [CI/CD](#9-cicd)
10. [Observability](#10-observability)
11. [Evals](#11-evals)
12. [Secret rotation](#12-secret-rotation)
13. [Operational tasks](#13-operational-tasks)
14. [Rollback](#14-rollback)
15. [Troubleshooting](#15-troubleshooting)
16. [Known limitations and gotchas](#16-known-limitations-and-gotchas)

---

## 1. Prerequisites

Local tooling:

- Python 3.11 or 3.12 (matches CI matrix)
- `uv` for dependency management (`pipx install uv`)
- Docker (for building the container image)
- `az` CLI (Azure)
- `terraform` 1.6+
- `gh` (optional, for managing CI/PRs)
- `ngrok` (only for local DocuSign Connect / Teams testing through a public URL)

Accounts and access:

- Azure subscription with **Owner** or **Contributor + User Access Administrator** on the target resource group (RBAC assignments require this).
- Microsoft 365 tenant with admin consent rights (Graph application permissions + Teams bot registration).
- DocuSign developer account (demo) for first-time setup; a production DocuSign account for go-live.
- An LLM provider key — Anthropic, Gemini, or an Azure OpenAI deployment in the same tenant.
- (Optional) Phoenix Cloud account for hosted LLM traces.

Repo clone:

```bash
git clone https://github.com/mdoyle11/onboarding_agent.git
cd onboarding_agent
uv sync                          # installs runtime + dev deps from uv.lock
```

---

## 2. One-time external setup

These steps mint identity, credentials, and external-system records. Run them once per environment (dev / prod). The interactive scripts under `scripts/` walk through each portal step and capture the values you'll paste into `.env`.

### 2.1 Azure AD application + Bot registration

```bash
uv run python scripts/setup_azure_ad.py
```

Captures:

- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
- `GRAPH_EXCEL_DRIVE_ID`, `GRAPH_EXCEL_ITEM_ID`, `GRAPH_EXCEL_SHEET_NAME`
- `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`
- `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`

Required Graph **application** permissions (with tenant admin consent):

- `Files.ReadWrite.All` — Excel tracker, rosters, separations
- `ChannelMessage.Send`, `Chat.Create`, `User.Read.All` — Teams proactive messaging
- `Mail.Send` — Outlook email from `OUTLOOK_SENDER_EMAIL`

The Azure Bot resource itself is provisioned by Terraform (`azapi` resource in `foundation/main.tf`). The script's bot-registration steps exist for legacy / manual flows; for fresh installs you can skip the portal bot creation and let Terraform create it, then plug `MICROSOFT_APP_ID` and `MICROSOFT_APP_PASSWORD` into tfvars.

### 2.2 Microsoft Graph — find Excel IDs

If you didn't capture them above:

```bash
uv run python scripts/find_excel_ids.py
```

Explores drives and sites with the credentials in `.env`, prints `drive_id` / `item_id` / `sheet_name` triples for each workbook. Use one row for the tracker and one per staff-roster location.

### 2.3 DocuSign — keys, app, consent

Single guided wizard (recommended):

```bash
uv run python scripts/setup_docusign.py
```

Or just the key pair:

```bash
uv run python scripts/generate_docusign_keys.py
```

This generates:

- `docusign_private.key` (mode `600`, **local-only, never commit**)
- `docusign_public.pem` (upload to DocuSign Integration Key → RSA Keys)

After uploading the public key, grant impersonation consent **once per environment** by opening:

```
https://account-d.docusign.com/oauth/auth?response_type=code
  &scope=signature%20impersonation
  &client_id=<INTEGRATION_KEY>
  &redirect_uri=https://www.docusign.com
```

(For production DocuSign, swap `account-d` for `account` and the demo base URL for the live one — see step 12.4.)

Captures:

- `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`
- `DOCUSIGN_PRIVATE_KEY_PATH` (local path) — **prod** stores the PEM in Key Vault as `docusign_private_key`
- `DOCUSIGN_TEMPLATE_ID` (an envelope template with at least one signer role)
- `DOCUSIGN_BASE_URL` (`https://demo.docusign.net/restapi` for dev, `https://na2.docusign.net/restapi` etc. for prod)
- `DOCUSIGN_CONNECT_URL` (public HTTPS URL where DocuSign Connect posts events — the Container App's FQDN in deployed envs, ngrok locally)

DocuSign Connect must be configured to POST to `${DOCUSIGN_CONNECT_URL}/webhook/docusign?secret=${WEBHOOK_SECRET}` with **envelope-level events: sent, delivered, completed, declined, voided**.

### 2.4 Outlook sender

`OUTLOOK_SENDER_EMAIL` must be a real mailbox in your tenant that the registered Azure AD app has `Mail.Send` permission for. No additional setup beyond admin consent.

### 2.5 LLM provider

Choose one of:

- **Anthropic** — set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.
- **Gemini** — set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`).
- **Azure OpenAI** — set `LLM_PROVIDER=azure_openai`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`, and either `AZURE_OPENAI_API_KEY` (dev) or `AZURE_OPENAI_MANAGED_IDENTITY_CLIENT_ID` (prod, recommended — the foundation Terraform provisions the role assignment).

---

## 3. Local development

```bash
cp .env.example .env
# fill in values from section 2

uv sync
uv run python -m onboarding_agent.server
```

Defaults for local mode (no Azure resources required):

- `STATE_STORE_BACKEND=file` — writes JSON under `./state/`
- `JOB_QUEUE_BACKEND=local` — in-process asyncio
- `OBSERVABILITY_ENABLED=false`

Expose the server publicly for Teams / DocuSign webhooks:

```bash
ngrok http 8080
# set DOCUSIGN_CONNECT_URL and the bot messaging endpoint to the ngrok URL
```

Run the unit tests:

```bash
uv run pytest tests/unit/ -v
```

Run the regression evals:

```bash
uv run python -m evals.run
```

Lint and type-check:

```bash
uv run ruff check src/ tests/
uv run mypy src/
```

---

## 4. Configuration reference

All config is read by `src/onboarding_agent/config.py` (pydantic-settings). Source of truth: `.env.example`. Group summary:

| Group | Keys |
|---|---|
| LLM provider | `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GEMINI_MODEL`, `AZURE_OPENAI_*` |
| Teams / Agents SDK | `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`, `MICROSOFT_APP_ALLOW_ANONYMOUS`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`, `TEAMS_LOADTEST_MODE` |
| Graph | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `GRAPH_EXCEL_*`, `STAFF_ROSTER_LOCATIONS_FILE` or `STAFF_ROSTER_LOCATIONS_JSON` |
| DocuSign | `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`, `DOCUSIGN_PRIVATE_KEY_PATH`/`DOCUSIGN_PRIVATE_KEY`, `DOCUSIGN_TEMPLATE_ID`, `DOCUSIGN_BASE_URL`, `DOCUSIGN_CONNECT_URL` |
| Outlook | `OUTLOOK_SENDER_EMAIL`, `EMAIL_TEMPLATE_PATH`, `EMAIL_SUBJECT_TEMPLATE`, `CLEAR_TO_START_CC_EMAILS`, `I9_DOCUMENTS_ATTACHMENT_PATH` |
| Server | `HOST`, `PORT`, `WEBHOOK_SECRET` |
| State | `STATE_STORE_BACKEND` (`file`/`cosmos`), `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE_NAME`, `COSMOS_CONTAINER_NAME`, `CONVERSATION_SESSION_COSMOS_CONTAINER_NAME` |
| Queue | `JOB_QUEUE_BACKEND` (`local`/`azure`), `AZURE_STORAGE_QUEUE_*`, `MANAGED_IDENTITY_CLIENT_ID`, `QUEUE_POLL_INTERVAL_SECONDS` |
| Observability | `OBSERVABILITY_ENABLED`, `OTEL_*`, `AZURE_MONITOR_*`, `PHOENIX_*`, `TRACE_*` |
| Evals | `EVALS_ENABLED`, `EVAL_SAMPLE_RATE` |

**Sensitive values that never live in `.env` in production** (they're Key Vault references in the app Terraform):

- `WEBHOOK_SECRET`
- `MICROSOFT_APP_PASSWORD`
- `AZURE_CLIENT_SECRET`
- `DOCUSIGN_PRIVATE_KEY` (the PEM body, not a path)

**Staff roster mapping (`config/staff_rosters.json`)**: per-location workbook IDs. Local-only / gitignored. The example shape is in `config/staff_rosters.example.json`. Before deploy, run `scripts/sync_staff_rosters_to_tfvars.sh` to inject this JSON into tfvars.

---

## 5. Infrastructure (Terraform)

Split into two layers under `infra/terraform/`:

- **`foundation/`** — long-lived shared resources. Apply once per environment, rarely touched after that.
- **`app/`** — the deployable workload. Re-applied on most deploys.

### 5.1 Foundation layer

Provisions:

- Resource group
- Log Analytics workspace + Application Insights
- Azure Container Registry (Basic, admin disabled — pulls use managed identity)
- Storage account
- Cosmos DB account
- Key Vault
- Shared user-assigned managed identity (with ACR pull, Key Vault secrets user, Azure OpenAI user roles)
- Container Apps environment
- Azure OpenAI account + model deployment (when used)
- Azure Bot resource (`azapi`)

First-time apply:

```bash
cd infra/terraform/foundation
cp terraform.tfvars.example terraform-dev.tfvars   # edit
terraform init
terraform plan  -var-file=terraform-dev.tfvars
terraform apply -var-file=terraform-dev.tfvars
```

Capture the outputs (`terraform output`) — the app layer needs:

- `container_app_environment_id`
- `container_registry_login_server`
- `cosmos_account_name`, `cosmos_endpoint`
- `storage_account_name`
- `key_vault_id`
- `shared_user_assigned_identity_id`, `shared_user_assigned_identity_client_id`
- `application_insights_connection_string`
- `azure_openai_endpoint`, `azure_openai_deployment_name`

### 5.2 App layer

Provisions:

- Container App (pulls image from ACR by managed identity)
- App-specific Cosmos SQL database + containers (`state-records`, `conversation-sessions`)
- Azure Storage queue
- Container App secrets — Key Vault-backed for the four sensitive secrets, inline for Cosmos key / roster JSON

Populate `infra/terraform/app/terraform-dev.tfvars` (or `terraform-prod.tfvars`) with foundation outputs plus app-only values (image tag, env-specific bot IDs, etc.). Then:

```bash
cd infra/terraform/app
scripts/sync_staff_rosters_to_tfvars.sh terraform-dev.tfvars   # injects roster JSON
terraform init
terraform plan  -var-file=terraform-dev.tfvars
terraform apply -var-file=terraform-dev.tfvars
```

The app's bot messaging endpoint is set automatically from the Container App FQDN — no portal step needed after the first apply.

### 5.3 State

`*.tfstate` files are currently local to each layer directory (see `infra/terraform/*/terraform.tfstate`). For team handover, move both layers to a remote backend (recommended: an Azure Storage container in the foundation resource group). Until then, **back up `terraform.tfstate` after every apply**.

---

## 6. Build and deploy

### 6.1 Build and push the image

```bash
scripts/build_and_push_container_app.sh <acr-name> <image-tag> [image-repo]
# example
scripts/build_and_push_container_app.sh onboardingagentprodacr 2026-05-19-abc1234 onboarding-agent
```

Notes:

- The script runs `az acr login`, then `docker build` and `docker push`.
- Use immutable tags (commit SHA or date+SHA) — never `latest` in prod.
- The Dockerfile copies `attachments/` into the image so the I-9 PDF ships with the build.

### 6.2 Roll the Container App to the new image

Update `image_tag` in the active tfvars file, then `terraform apply` in `infra/terraform/app/`. The Container App will create a new revision with the new image; traffic shifts according to your revision-mode setting (single-revision mode by default — the new revision replaces the old one).

> ⚠️ `scripts/deploy_container_app.sh` is **legacy** and points to a removed `infra/terraform/container-app/` directory. Don't use it — apply `foundation/` and `app/` directly with `terraform apply` until the script is updated.

---

## 7. Teams app packaging and sideload

```bash
scripts/package_teams_app.sh <bot-host> <bot-app-id> [teams-app-id]
# example
scripts/package_teams_app.sh onboarding-agent.eastus.azurecontainerapps.io 00000000-0000-0000-0000-000000000000
```

Renders `teamsappPackage/manifest.json` (template, not committed in real form — see `teamsappPackage.example/` for the safe template), zips it with `color.png` / `outline.png`, and writes `teamsappPackage/onboarding-agent-teams-app.zip`.

Upload steps:

1. Teams Admin Center → Teams apps → Manage apps → Upload new app
2. Pick the generated zip
3. Approve org-wide (or scope to the HR team)
4. Add the app in the target channel / DMs

Re-run this whenever the bot host changes (e.g. a new region or a custom domain). The bot's messaging endpoint inside the Bot Service is already set by Terraform — the manifest only declares the validDomains and the `botId`.

---

## 8. Smoke tests

After every deploy, run:

### 8.1 Health probe

```bash
curl https://<host>/api/messages
# expect 200 "ok"
```

### 8.2 New-hire webhook

```bash
curl -X POST "https://<host>/webhook/new-hire" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <WEBHOOK_SECRET>" \
  -d @tests/fixtures/new_hire_sample.json
# expect 200 {"ok":true,"status":"accepted"}
```

Verify in Teams that the new-hire adaptive card appears in the HR channel within ~30 seconds, and that the tracker row is created in the Excel workbook.

### 8.3 DocuSign Connect webhook

```bash
scripts/test_docusign_webhook.sh <envelope-id> <employee-email> <base-url>
```

`/webhook/docusign` does **not** require the shared secret — DocuSign Connect is trusted by source. Verify the DocuSign status card posts/updates and the tracker stage advances.

### 8.4 Teams chat

In Teams, DM the bot:

> What's the onboarding status for `<test employee>`?

Expect a structured response sourced from tracker + DocuSign. Also try one card-button click ("Send Welcome Email" or "Send Offer Letter") and confirm the side effect lands.

### 8.5 Background-clearance webhook

```bash
curl -X POST "https://<host>/webhook/background-clearance" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <WEBHOOK_SECRET>" \
  -d '{"employee_email":"test@example.com","status":"clear"}'
```

Verify confirmation email is sent and the tracker is updated.

---

## 9. CI/CD

`.github/workflows/ci.yml` runs on every PR to `main` / `develop` and every push to `main`. Matrix: Python 3.11 and 3.12. Jobs:

1. `pip install -e ".[dev]"`
2. `ruff check src/ tests/`
3. `mypy src/`
4. `pytest tests/unit/ -v --tb=short` (with stubbed env vars so `config.py` import succeeds)
5. `python -m evals.run` (regression eval suite)

**Required GitHub secrets for full CI** (optional — fallbacks exist for most):

- `ANTHROPIC_API_KEY` (only needed if you want eval cases to run against a real LLM; stub works for parser-level cases)
- The Azure / DocuSign secrets in `ci.yml` are stubbed by default — set real values only for end-to-end CI runs.

There is currently **no automated deploy job**. Deploys are manual:

1. Merge to `main`
2. Wait for green CI
3. Run `scripts/build_and_push_container_app.sh` locally
4. Bump `image_tag` in tfvars and `terraform apply` the app layer
5. Run section 8 smoke tests

This is intentional for a single-maintainer project. To automate, add a workflow that runs after `lint-and-test` succeeds on `main`, OIDC-authenticates to Azure (`azure/login@v2` with a federated identity credential on the foundation's user-assigned identity), and re-runs the build + terraform-apply steps.

---

## 10. Observability

Configured in `src/onboarding_agent/observability/setup.py`. All exporters are off by default.

### 10.1 Azure Monitor (Application Insights)

- `AZURE_MONITOR_ENABLED=true`
- `AZURE_MONITOR_CONNECTION_STRING=<connection string from foundation output>`

The app layer's Terraform plumbs this automatically from `application_insights_connection_string`. Once on, traces and logs flow to the Application Insights resource in the foundation RG. The Log Analytics workspace backs it.

Useful Kusto queries (Application Insights → Logs):

```kusto
// All errors in the last hour
exceptions
| where timestamp > ago(1h)
| project timestamp, operation_Name, type, outerMessage

// Slow webhook handling
requests
| where timestamp > ago(24h) and name startswith "POST /webhook/"
| summarize p50=percentile(duration, 50), p95=percentile(duration, 95) by name

// Agent loop tool calls
dependencies
| where timestamp > ago(1h) and name startswith "agent.tool"
| project timestamp, name, success, duration, customDimensions
```

### 10.2 Phoenix (LLM-trace UI)

- `PHOENIX_ENABLED=true`
- `PHOENIX_ENDPOINT=https://app.phoenix.arize.com/v1/traces` (or self-hosted)
- `PHOENIX_API_KEY=<key>` — Key Vault-backed in prod
- `PHOENIX_PROJECT_NAME=onboarding-agent-prod`
- `PHOENIX_SPAN_NAME_PREFIXES=teams.,agent.,tracker.,graph.excel.tracker.`

Phoenix gets a filtered view (the span-name prefix list controls what gets exported), so LLM-relevant spans don't drown in low-level HTTP noise.

### 10.3 Trace controls

- `TRACE_SAMPLE_RATE` — 0.0 to 1.0; defaults to 1.0 (capture everything). Lower in prod if cost matters.
- `TRACE_CAPTURE_FULL_PAYLOADS=false` — keep `false` in prod. When `true`, full LLM input/output payloads are attached to spans (useful for debugging, expensive at volume, PII-sensitive).
- `TRACE_HASH_SALT` — used by `observability/pii.py` to hash employee identifiers in span attributes deterministically. **Rotate when changing tenants or revoking historical traces.**

### 10.4 PII redaction

`observability/pii.py` redacts emails, names, and free-text payloads in span attributes and log output. Verify after any change to that module by running:

```bash
uv run pytest tests/unit/observability/
```

---

## 11. Evals

Two evaluation surfaces:

### 11.1 Regression evals (`evals/`)

Deterministic, run in CI. Each `evals/cases/*.json` declares a `type`:

- `trace_behavior` — replays a recorded message + tool transcript and checks the `evaluate_agent_response` heuristics (clarification, failure handling).
- `stage_resolution` — exercises the relaxed-field-name resolution in the tracker tool.
- `vacancy_filter` — checks roster-vacancy filtering logic.

Run locally:

```bash
uv run python -m evals.run
# add a new case
cp evals/cases/relaxed_stage_name_background_submission.json evals/cases/my_new_case.json
```

Exit code is non-zero if any case fails — that's the CI signal.

### 11.2 Production evals (`observability/evals.py`)

When `EVALS_ENABLED=true`, a sampled fraction (`EVAL_SAMPLE_RATE`, e.g. `0.05`) of agent turns get scored on the same heuristics (clarification quality, failure-mode detection) and the results are attached as OpenTelemetry span events. Browse them in Application Insights or Phoenix to spot regression patterns in production traffic.

Turn it on cautiously — at 100% sampling it doubles span attribute volume. 5–10% is a good default.

---

## 12. Secret rotation

### 12.1 `WEBHOOK_SECRET`

1. Generate: `openssl rand -hex 32`
2. Update the `webhook_secret` Key Vault secret (`az keyvault secret set ...`)
3. The Container App pulls Key Vault refs at revision start, so trigger a new revision: bump a no-op env var or re-apply `app/` Terraform.
4. Update the Power Automate flow's `X-Webhook-Secret` header.
5. Update the background-clearance caller's `X-Webhook-Secret` header.
6. Decommission old secret only after confirming the new one is live for both callers. (DocuSign Connect does not use this secret.)

### 12.2 `MICROSOFT_APP_PASSWORD`

1. Azure Portal → App registrations → your bot app → Certificates & secrets → New client secret.
2. Update `microsoft_app_password` Key Vault secret.
3. Trigger a new Container App revision.
4. Delete the old secret in the portal after 24h grace.

### 12.3 `AZURE_CLIENT_SECRET`

Same flow as `MICROSOFT_APP_PASSWORD`, but for the Graph app registration. After rotation, run a smoke test that exercises Graph (the new-hire webhook smoke test does this).

### 12.4 DocuSign private key

1. Generate a new key pair with `scripts/generate_docusign_keys.py`.
2. Upload the new public key to DocuSign Integration Key → RSA Keys (keep the old one until cutover).
3. Update the `docusign_private_key` Key Vault secret with the new PEM body.
4. Trigger a new Container App revision.
5. Delete the old public key in DocuSign.

> **Demo → production cutover:** the demo and live DocuSign accounts are entirely separate — separate user IDs, integration keys, consent grants, base URLs, and Connect endpoints. Treat the cutover as a full re-do of section 2.3 against the production console, then swap `DOCUSIGN_BASE_URL` and all four DocuSign env vars at once.

### 12.5 LLM API key

Update the relevant Key Vault secret (or env var for dev), then trigger a new revision. No traffic shaping needed — the agent picks up the new credential on the next turn.

---

## 13. Operational tasks

### 13.1 Inspect live state

```bash
# View Container App logs (last 1h)
az containerapp logs show \
  --name onboarding-agent --resource-group <rg> \
  --tail 200 --follow

# View revisions
az containerapp revision list \
  --name onboarding-agent --resource-group <rg> -o table

# Inspect a Cosmos state record
az cosmosdb sql query \
  --account-name <cosmos-account> --resource-group <rg> \
  --database-name onboarding-agent --container-name state-records \
  --query-text "SELECT * FROM c WHERE c.id = 'new_hire_card:<email>'"
```

### 13.2 Clear runtime state for a test employee

```bash
uv run python scripts/reset_runtime_state.py \
  --cosmos-endpoint https://<account>.documents.azure.com:443/ \
  --cosmos-key "$(az cosmosdb keys list --name <account> --resource-group <rg> --query primaryMasterKey -o tsv)" \
  --database onboarding-agent \
  --container state-records \
  --employee-email test.user@example.com \
  --all-conversation-refs
```

Wipes new-hire card, DocuSign status card, and conversation references for that employee. Tracker rows in Excel are **not** touched — delete them manually in the workbook if needed.

### 13.3 Drain the queue

If the worker is stuck on a poison message, peek and remove:

```bash
az storage message peek --queue-name onboarding-jobs \
  --account-name <storage> --num-messages 10

# After identifying a bad message:
az storage message clear --queue-name onboarding-jobs --account-name <storage>
```

The dispatcher in `runtime/jobs.process_job` logs the message body and `kind` before doing any work, so the offending payload is grep-able in Application Insights.

### 13.4 Re-sync staff rosters

After editing `config/staff_rosters.json`:

```bash
scripts/sync_staff_rosters_to_tfvars.sh infra/terraform/app/terraform-prod.tfvars
cd infra/terraform/app
terraform apply -var-file=terraform-prod.tfvars
```

The roster JSON ships to the Container App as the `STAFF_ROSTER_LOCATIONS_JSON` env var (inline secret), so it's picked up on the next revision.

### 13.5 Pause traffic

Scale the Container App to zero replicas:

```bash
az containerapp update \
  --name onboarding-agent --resource-group <rg> \
  --min-replicas 0 --max-replicas 0
```

To resume, set `--min-replicas 1` (or whatever the tfvars default is). Webhook callers will retry; the queue persists pending work.

---

## 14. Rollback

The app is single-revision-mode by default, but old revisions are retained for ~7 days. To roll back:

```bash
# List revisions
az containerapp revision list \
  --name onboarding-agent --resource-group <rg> \
  -o table

# Activate the previous revision and shift traffic
az containerapp revision activate \
  --name onboarding-agent --resource-group <rg> \
  --revision <previous-revision-name>

az containerapp ingress traffic set \
  --name onboarding-agent --resource-group <rg> \
  --revision-weight <previous-revision-name>=100
```

For a Terraform-tracked rollback, re-apply the app layer with the previous `image_tag` value (commit SHA). This is the preferred path — keeps tfstate honest.

---

## 15. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Teams 401 / "unauthorized" | `MICROSOFT_APP_PASSWORD` rotated, not propagated to Container App | Re-apply app layer; trigger new revision |
| Teams "service unavailable" briefly after deploy | Cold start | Wait 30–60s; set `min_replicas=1` to keep warm |
| Webhook 403 | Wrong/missing `X-Webhook-Secret` header | Compare `WEBHOOK_SECRET` env var to caller config |
| New-hire card never appears | Job stuck in queue, or Graph permission missing | Check Storage Queue depth + Application Insights `exceptions` table |
| DocuSign callbacks not arriving | DocuSign Connect URL or secret wrong | Re-check DocuSign Admin → Connect; resend a recent failed event from Connect logs |
| Excel writes fail with 403 | Graph admin consent reverted | Re-grant `Files.ReadWrite.All` in Azure portal |
| Agent loops forever / hits `_MAX_TOOL_LOOPS` | Bad tool schema or missing data | Check Phoenix trace for the loop; usually a tool returning ambiguous results |
| `pytest` fails on import | Required env var missing | The CI workflow shows the minimum stub set in `ci.yml` |
| Terraform plan wants to recreate Cosmos | `free_tier_enabled` flip or rename | Cosmos free-tier is one-per-subscription — only one account can claim it. Edit tfvars or import the existing account |
| `cryptography` import error in CI | Missing libssl | The default ubuntu-latest image has it; check Python version |

For agent-level debugging, the most useful tool is Phoenix: filter by the user's email or session ID and replay the conversation including every tool call and LLM response.

---

## 16. Known limitations and gotchas

- **`scripts/deploy_container_app.sh` is stale.** It targets `infra/terraform/container-app/` which was removed when the split happened. Use `terraform apply` in `foundation/` and `app/` directly. Either update or delete the script.
- **Terraform state is local.** Both layers store state on disk. Move to a remote backend before any second maintainer joins. Back up `terraform.tfstate*` after every apply.
- **No automated deploy.** CI runs lint/test/eval only. Production deploys are manual (build image → bump tag → `terraform apply` → smoke test).
- **One Container App, no separate worker tier.** The same process serves Teams traffic and drains the queue. Under a sustained burst this can starve interactive responsiveness. The code is structured to split (pluggable queue / store backends), but no infra split exists today. See `ARCHITECTURE.md` for the relevant abstraction points.
- **`MICROSOFT_APP_ALLOW_ANONYMOUS` and `TEAMS_LOADTEST_MODE` must be `false` in production.** They exist only for local Bot Framework Emulator testing.
- **DocuSign demo vs prod URLs are different hostnames.** A common deploy mistake is leaving `DOCUSIGN_BASE_URL` on `demo.docusign.net` after a production cutover; the JWT auth will fail with confusing errors.
- **Cosmos free-tier is one-per-subscription.** If a prior project claimed it, the foundation Terraform will fail until `cosmos_free_tier_enabled=false`.
- **Excel as a database has rate limits.** Graph throttles burst writes around ~10 ops/sec for a single workbook. The tracker client retries with backoff, but very chatty workflows will queue up. Watch the `graph.excel.tracker.*` spans in Phoenix for outliers.
- **Memory-only Teams adapter storage.** The Agents SDK is initialized with `MemoryStorage()` — Teams turn state does not survive restarts. Durable conversation history lives in Cosmos (`conversation-sessions`), but anything held only in adapter state (rare) is lost on revision swap.

---

## Appendix: scripts at a glance

| Script | Purpose |
|---|---|
| `scripts/setup_azure_ad.py` | Interactive walkthrough for Entra ID app, Graph permissions, Teams IDs |
| `scripts/setup_docusign.py` | End-to-end DocuSign JWT Grant setup |
| `scripts/generate_docusign_keys.py` | RSA key pair only |
| `scripts/find_excel_ids.py` | Discover Graph drive / item / sheet IDs |
| `scripts/build_and_push_container_app.sh` | `az acr login` → `docker build` → `docker push` |
| `scripts/sync_staff_rosters_to_tfvars.sh` | Inject `config/staff_rosters.json` into tfvars |
| `scripts/package_teams_app.sh` | Render manifest + zip Teams sideload package |
| `scripts/reset_runtime_state.py` | Delete Cosmos state for a test employee |
| `scripts/test_docusign_webhook.sh` | Curl a synthetic DocuSign Connect event |
| `scripts/deploy_container_app.sh` | ⚠️ Legacy — points to removed `container-app/` Terraform dir |
