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
    STAFF_ROSTER_DEFAULT_SEPARATIONS_SHEET_NAME = var.staff_roster_default_separations_sheet_name
  }

  key_vault_secret_env_vars = {
    WEBHOOK_SECRET         = "webhook_secret"
    MICROSOFT_APP_PASSWORD = "microsoft_app_password"
    AZURE_CLIENT_SECRET    = "azure_client_secret"
    DOCUSIGN_PRIVATE_KEY   = "docusign_private_key"
  }

  inline_secret_env_vars = {
    COSMOS_KEY                  = "cosmos-key"
    STAFF_ROSTER_LOCATIONS_JSON = "staff-roster-locations-json"
  }

  key_vault_secret_ids = {
    for env_name, secret_key in local.key_vault_secret_env_vars :
    env_name => data.azurerm_key_vault_secret.app[secret_key].versionless_id
  }

  inline_container_app_secrets = {
    "cosmos-key"                  = var.cosmos_key
    "staff-roster-locations-json" = var.staff_roster_locations_json
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
