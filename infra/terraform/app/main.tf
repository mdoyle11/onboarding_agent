locals {
  base_tags = merge(
    {
      project     = var.project_name
      environment = var.environment
      managed_by  = "terraform"
      layer       = "app"
    },
    var.tags
  )

  image = "${data.azurerm_container_registry.foundation.login_server}/${var.project_name}:${var.image_tag}"

  env_vars = {
    LLM_PROVIDER                                = var.llm_provider
    GEMINI_MODEL                                = var.gemini_model
    AZURE_OPENAI_ENDPOINT                       = var.azure_openai_endpoint
    AZURE_OPENAI_API_VERSION                    = var.azure_openai_api_version
    AZURE_OPENAI_DEPLOYMENT                     = var.azure_openai_deployment
    AZURE_OPENAI_MANAGED_IDENTITY_CLIENT_ID     = var.shared_user_assigned_identity_client_id
    HOST                                        = "0.0.0.0"
    PORT                                        = "8080"
    MICROSOFT_APP_ID                            = var.microsoft_app_id
    MICROSOFT_APP_ALLOW_ANONYMOUS               = tostring(var.microsoft_app_allow_anonymous)
    TEAMS_LOADTEST_MODE                         = tostring(var.teams_loadtest_mode)
    AZURE_TENANT_ID                             = var.azure_tenant_id
    AZURE_CLIENT_ID                             = var.azure_client_id
    GRAPH_EXCEL_DRIVE_ID                        = var.graph_excel_drive_id
    GRAPH_EXCEL_ITEM_ID                         = var.graph_excel_item_id
    GRAPH_EXCEL_TABLE_NAME                      = var.graph_excel_table_name
    DOCUSIGN_ACCOUNT_ID                         = var.docusign_account_id
    DOCUSIGN_INTEGRATION_KEY                    = var.docusign_integration_key
    DOCUSIGN_USER_ID                            = var.docusign_user_id
    DOCUSIGN_TEMPLATE_ID                        = var.docusign_template_id
    DOCUSIGN_CONNECT_URL                        = var.docusign_connect_url
    TEAMS_CHANNEL_ID                            = var.teams_channel_id
    OUTLOOK_SENDER_EMAIL                        = var.outlook_sender_email
    STATE_STORE_BACKEND                         = var.state_store_backend
    COSMOS_ENDPOINT                             = data.azurerm_cosmosdb_account.foundation.endpoint
    COSMOS_DATABASE_NAME                        = var.cosmos_database_name
    COSMOS_CONTAINER_NAME                       = var.cosmos_state_container_name
    CONVERSATION_SESSION_COSMOS_CONTAINER_NAME  = var.conversation_session_cosmos_container_name
    JOB_QUEUE_BACKEND                           = "azure"
    MANAGED_IDENTITY_CLIENT_ID                  = var.shared_user_assigned_identity_client_id
    AZURE_STORAGE_QUEUE_NAME                    = var.azure_storage_queue_name
    AZURE_STORAGE_QUEUE_ACCOUNT_URL             = "https://${data.azurerm_storage_account.foundation.name}.queue.core.windows.net"
    QUEUE_POLL_INTERVAL_SECONDS                 = tostring(var.queue_poll_interval_seconds)
    STAFF_ROSTER_DEFAULT_SEPARATIONS_SHEET_NAME = var.staff_roster_default_separations_sheet_name
    OBSERVABILITY_ENABLED                       = tostring(var.observability_enabled)
    OTEL_SERVICE_NAME                           = var.otel_service_name
    OTEL_ENVIRONMENT                            = var.environment
    OTEL_SERVICE_VERSION                        = var.image_tag
    AZURE_MONITOR_ENABLED                       = tostring(var.azure_monitor_enabled)
    AZURE_MONITOR_CONNECTION_STRING             = var.application_insights_connection_string
    PHOENIX_ENABLED                             = tostring(var.phoenix_enabled)
    PHOENIX_ENDPOINT                            = var.phoenix_endpoint
    PHOENIX_PROJECT_NAME                        = var.phoenix_project_name
    PHOENIX_OTLP_HEADERS                        = var.phoenix_otlp_headers
    PHOENIX_SPAN_NAME_PREFIXES                  = var.phoenix_span_name_prefixes
    TRACE_SAMPLE_RATE                           = tostring(var.trace_sample_rate)
    TRACE_CAPTURE_FULL_PAYLOADS                 = tostring(var.trace_capture_full_payloads)
    EVALS_ENABLED                               = tostring(var.evals_enabled)
    EVAL_SAMPLE_RATE                            = tostring(var.eval_sample_rate)
  }

  key_vault_secret_env_vars = {
    WEBHOOK_SECRET         = "webhook_secret"
    MICROSOFT_APP_PASSWORD = "microsoft_app_password"
    AZURE_CLIENT_SECRET    = "azure_client_secret"
    DOCUSIGN_PRIVATE_KEY   = "docusign_private_key"
  }

  inline_secret_env_vars = merge(
    {
      COSMOS_KEY                  = "cosmos-key"
      STAFF_ROSTER_LOCATIONS_JSON = "staff-roster-locations-json"
    },
    var.phoenix_api_key != "" ? { PHOENIX_API_KEY = "phoenix-api-key" } : {},
    var.trace_hash_salt != "" ? { TRACE_HASH_SALT = "trace-hash-salt" } : {},
  )

  key_vault_secret_ids = {
    for env_name, secret_key in local.key_vault_secret_env_vars :
    env_name => data.azurerm_key_vault_secret.app[secret_key].versionless_id
  }

  inline_container_app_secrets = merge(
    {
      "cosmos-key"                  = var.cosmos_key
      "staff-roster-locations-json" = var.staff_roster_locations_json
    },
    var.phoenix_api_key != "" ? { "phoenix-api-key" = var.phoenix_api_key } : {},
    var.trace_hash_salt != "" ? { "trace-hash-salt" = var.trace_hash_salt } : {},
  )

  monitor_alerts_enabled = var.azure_monitor_alerts_enabled && length(var.azure_monitor_alert_email_receivers) > 0

  monitor_alert_queries = {
    app_exceptions = {
      description = "Application exceptions were recorded for the onboarding agent."
      severity    = 2
      frequency   = "PT5M"
      window      = "PT15M"
      operator    = "GreaterThan"
      threshold   = 0
      query       = <<-KQL
        union isfuzzy=true AppExceptions, exceptions
        | where tostring(column_ifexists("AppRoleName", column_ifexists("cloud_RoleName", ""))) == "${var.otel_service_name}"
        | summarize Count = count()
      KQL
    }

    tool_exceptions = {
      description = "One or more agent tool calls raised an exception."
      severity    = 2
      frequency   = "PT5M"
      window      = "PT15M"
      operator    = "GreaterThan"
      threshold   = 0
      query       = <<-KQL
        union isfuzzy=true AppDependencies, dependencies, AppTraces, traces
        | extend dims = todynamic(column_ifexists("Properties", column_ifexists("customDimensions", dynamic({}))))
        | where tostring(dims["onboarding.tool_failed"]) == "true"
        | summarize Count = count()
      KQL
    }

    online_eval_failures = {
      description = "Online agent evaluations detected failed behavior checks."
      severity    = 3
      frequency   = "PT15M"
      window      = "PT30M"
      operator    = "GreaterThan"
      threshold   = 0
      query       = <<-KQL
        union isfuzzy=true AppDependencies, dependencies, AppTraces, traces
        | extend dims = todynamic(column_ifexists("Properties", column_ifexists("customDimensions", dynamic({}))))
        | where toint(dims["onboarding.evals.failed_count"]) > 0 or tostring(dims["onboarding.evals.all_passed"]) == "false"
        | summarize Count = count()
      KQL
    }

    no_telemetry = {
      description = "No onboarding-agent telemetry was received in the lookback window."
      severity    = 2
      frequency   = "PT15M"
      window      = "PT30M"
      operator    = "LessThan"
      threshold   = 1
      query       = <<-KQL
        union isfuzzy=true AppRequests, requests, AppDependencies, dependencies, AppTraces, traces
        | extend dims = todynamic(column_ifexists("Properties", column_ifexists("customDimensions", dynamic({}))))
        | extend role = tostring(column_ifexists("AppRoleName", column_ifexists("cloud_RoleName", "")))
        | where role == "${var.otel_service_name}" or tostring(dims["service.name"]) == "${var.otel_service_name}"
        | summarize Count = count()
      KQL
    }
  }
}

data "azurerm_resource_group" "foundation" {
  name = var.resource_group_name
}

data "azurerm_container_registry" "foundation" {
  name                = var.container_registry_name
  resource_group_name = data.azurerm_resource_group.foundation.name
}

data "azurerm_key_vault" "foundation" {
  name                = var.key_vault_name
  resource_group_name = data.azurerm_resource_group.foundation.name
}

data "azurerm_storage_account" "foundation" {
  name                = var.storage_account_name
  resource_group_name = data.azurerm_resource_group.foundation.name
}

data "azurerm_cosmosdb_account" "foundation" {
  name                = var.cosmos_account_name
  resource_group_name = data.azurerm_resource_group.foundation.name
}

data "azurerm_key_vault_secret" "app" {
  for_each = var.key_vault_secret_names

  name         = each.value
  key_vault_id = data.azurerm_key_vault.foundation.id
}

resource "azurerm_storage_queue" "jobs" {
  name                 = var.azure_storage_queue_name
  storage_account_name = data.azurerm_storage_account.foundation.name
}

resource "azurerm_cosmosdb_sql_database" "app" {
  name                = var.cosmos_database_name
  resource_group_name = data.azurerm_resource_group.foundation.name
  account_name        = data.azurerm_cosmosdb_account.foundation.name
}

resource "azurerm_cosmosdb_sql_container" "state_records" {
  name                = var.cosmos_state_container_name
  resource_group_name = data.azurerm_resource_group.foundation.name
  account_name        = data.azurerm_cosmosdb_account.foundation.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_paths = ["/namespace"]
}

resource "azurerm_cosmosdb_sql_container" "conversation_sessions" {
  name                = var.conversation_session_cosmos_container_name
  resource_group_name = data.azurerm_resource_group.foundation.name
  account_name        = data.azurerm_cosmosdb_account.foundation.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_paths = ["/namespace"]
  default_ttl         = var.conversation_session_cosmos_default_ttl
}

resource "azurerm_container_app" "this" {
  name                         = var.container_app_name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = data.azurerm_resource_group.foundation.name
  revision_mode                = "Single"
  tags                         = local.base_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.shared_user_assigned_identity_id]
  }

  dynamic "secret" {
    for_each = local.inline_container_app_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  dynamic "secret" {
    for_each = local.key_vault_secret_ids
    content {
      name                = data.azurerm_key_vault_secret.app[local.key_vault_secret_env_vars[secret.key]].name
      key_vault_secret_id = secret.value
      identity            = var.shared_user_assigned_identity_id
    }
  }

  registry {
    server   = data.azurerm_container_registry.foundation.login_server
    identity = var.shared_user_assigned_identity_id
  }

  ingress {
    allow_insecure_connections = false
    external_enabled           = true
    target_port                = 8080
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "onboarding-agent"
      image  = local.image
      cpu    = var.cpu
      memory = var.memory

      dynamic "env" {
        for_each = local.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.key_vault_secret_env_vars
        content {
          name        = env.key
          secret_name = data.azurerm_key_vault_secret.app[env.value].name
        }
      }

      dynamic "env" {
        for_each = local.inline_secret_env_vars
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}

resource "azapi_update_resource" "azure_bot_endpoint" {
  type        = "Microsoft.BotService/botServices@2023-09-15-preview"
  resource_id = var.azure_bot_resource_id

  body = jsonencode({
    properties = {
      endpoint = "https://${azurerm_container_app.this.ingress[0].fqdn}/api/messages"
    }
  })
}

resource "azurerm_monitor_action_group" "observability" {
  count = local.monitor_alerts_enabled ? 1 : 0

  name                = var.azure_monitor_action_group_name
  resource_group_name = data.azurerm_resource_group.foundation.name
  short_name          = var.azure_monitor_action_group_short_name
  tags                = local.base_tags

  dynamic "email_receiver" {
    for_each = var.azure_monitor_alert_email_receivers
    content {
      name          = email_receiver.key
      email_address = email_receiver.value
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "observability" {
  for_each = local.monitor_alerts_enabled ? local.monitor_alert_queries : {}

  name                 = "${var.container_app_name}-${each.key}"
  resource_group_name  = data.azurerm_resource_group.foundation.name
  location             = data.azurerm_resource_group.foundation.location
  scopes               = [var.log_analytics_workspace_id]
  description          = each.value.description
  enabled              = true
  severity             = each.value.severity
  evaluation_frequency = each.value.frequency
  window_duration      = each.value.window
  tags                 = local.base_tags

  criteria {
    query                   = each.value.query
    time_aggregation_method = "Maximum"
    metric_measure_column   = "Count"
    operator                = each.value.operator
    threshold               = each.value.threshold

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.observability[0].id]
  }
}
