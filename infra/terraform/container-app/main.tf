locals {
  base_tags = merge(
    {
      project     = var.project_name
      environment = var.environment
      managed_by  = "terraform"
    },
    var.tags
  )

  image = "${data.azurerm_container_registry.existing.login_server}/${var.project_name}:${var.image_tag}"

  # Non-secret environment variables
  env_vars = {
    LLM_PROVIDER                           = var.llm_provider
    GEMINI_MODEL                           = var.gemini_model
    HOST                                   = "0.0.0.0"
    PORT                                   = "8080"
    MICROSOFT_APP_ID                       = var.microsoft_app_id
    AZURE_TENANT_ID                        = var.azure_tenant_id
    AZURE_CLIENT_ID                        = var.azure_client_id
    GRAPH_EXCEL_DRIVE_ID                   = var.graph_excel_drive_id
    GRAPH_EXCEL_ITEM_ID                    = var.graph_excel_item_id
    DOCUSIGN_ACCOUNT_ID                    = var.docusign_account_id
    DOCUSIGN_INTEGRATION_KEY               = var.docusign_integration_key
    DOCUSIGN_USER_ID                       = var.docusign_user_id
    DOCUSIGN_TEMPLATE_ID                   = var.docusign_template_id
    DOCUSIGN_CONNECT_URL                   = var.docusign_connect_url
    TEAMS_CHANNEL_ID                       = var.teams_channel_id
    OUTLOOK_SENDER_EMAIL                   = var.outlook_sender_email
    STATE_STORE_BACKEND                    = var.state_store_backend
    COSMOS_ENDPOINT                        = data.azurerm_cosmosdb_account.existing.endpoint
    COSMOS_DATABASE_NAME                   = var.cosmos_database_name
    COSMOS_CONTAINER_NAME                  = var.cosmos_state_container_name
    JOB_QUEUE_BACKEND                      = "azure"
    AZURE_STORAGE_QUEUE_NAME               = var.azure_storage_queue_name
    GRAPH_CHECKPOINT_BACKEND               = var.graph_checkpoint_backend
    GRAPH_CHECKPOINT_COSMOS_DATABASE_NAME  = var.cosmos_database_name
    GRAPH_CHECKPOINT_COSMOS_CONTAINER_NAME = var.graph_checkpoint_cosmos_container_name
  }

  required_secret_env_vars = {
    WEBHOOK_SECRET                        = "webhook-secret"
    MICROSOFT_APP_PASSWORD                = "microsoft-app-password"
    AZURE_CLIENT_SECRET                   = "azure-client-secret"
    DOCUSIGN_PRIVATE_KEY                  = "docusign-private-key"
    COSMOS_KEY                            = "cosmos-key"
    AZURE_STORAGE_QUEUE_CONNECTION_STRING = "azure-storage-queue-connection-string"
    STAFF_ROSTER_LOCATIONS_JSON           = "staff-roster-locations-json"
  }

  optional_secret_env_vars = {
    ANTHROPIC_API_KEY = "anthropic-api-key"
    GEMINI_API_KEY    = "gemini-api-key"
  }

  enabled_optional_secret_env_vars = {
    for env_name, secret_name in local.optional_secret_env_vars :
    env_name => secret_name
    if(
      (env_name == "ANTHROPIC_API_KEY" && trimspace(var.anthropic_api_key) != "") ||
      (env_name == "GEMINI_API_KEY" && trimspace(var.gemini_api_key) != "")
    )
  }

  secret_env_vars = merge(
    local.required_secret_env_vars,
    local.enabled_optional_secret_env_vars
  )

  required_container_app_secrets = {
    "webhook-secret"                        = var.webhook_secret
    "microsoft-app-password"                = var.microsoft_app_password
    "azure-client-secret"                   = var.azure_client_secret
    "docusign-private-key"                  = var.docusign_private_key
    "cosmos-key"                            = var.cosmos_key
    "azure-storage-queue-connection-string" = var.storage_account_connection_string
    "staff-roster-locations-json"           = var.staff_roster_locations_json
    "registry-password"                     = var.container_registry_password
  }

  optional_container_app_secrets = {
    "anthropic-api-key" = var.anthropic_api_key
    "gemini-api-key"    = var.gemini_api_key
  }

  enabled_optional_container_app_secrets = {
    for name, value in local.optional_container_app_secrets :
    name => value if trimspace(value) != ""
  }

  container_app_secrets = merge(
    local.required_container_app_secrets,
    local.enabled_optional_container_app_secrets
  )
}

data "azurerm_cosmosdb_account" "existing" {
  name                = var.existing_cosmos_account_name
  resource_group_name = var.resource_group_name
}

data "azurerm_resource_group" "existing" {
  name = var.resource_group_name
}

data "azurerm_container_registry" "existing" {
  name                = var.container_registry_name
  resource_group_name = var.resource_group_name
}

data "azurerm_storage_account" "existing" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.project_name}-${var.environment}-logs"
  resource_group_name = data.azurerm_resource_group.existing.name
  location            = data.azurerm_resource_group.existing.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.base_tags
}

resource "azurerm_storage_queue" "jobs" {
  name                 = var.azure_storage_queue_name
  storage_account_name = data.azurerm_storage_account.existing.name
}

resource "azurerm_cosmosdb_sql_database" "app" {
  name                = var.cosmos_database_name
  resource_group_name = data.azurerm_cosmosdb_account.existing.resource_group_name
  account_name        = data.azurerm_cosmosdb_account.existing.name
}

resource "azurerm_cosmosdb_sql_container" "state_records" {
  name                = var.cosmos_state_container_name
  resource_group_name = data.azurerm_cosmosdb_account.existing.resource_group_name
  account_name        = data.azurerm_cosmosdb_account.existing.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_paths = ["/namespace"]
}

resource "azurerm_cosmosdb_sql_container" "graph_checkpoints" {
  name                = var.graph_checkpoint_cosmos_container_name
  resource_group_name = data.azurerm_cosmosdb_account.existing.resource_group_name
  account_name        = data.azurerm_cosmosdb_account.existing.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_paths = ["/partition_key"]
}

resource "azurerm_container_app_environment" "this" {
  name                       = var.container_app_environment_name
  resource_group_name        = data.azurerm_resource_group.existing.name
  location                   = data.azurerm_resource_group.existing.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.base_tags
}

resource "azurerm_container_app" "this" {
  name                         = var.container_app_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = data.azurerm_resource_group.existing.name
  revision_mode                = "Single"
  tags                         = local.base_tags

  dynamic "secret" {
    for_each = local.container_app_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  registry {
    server               = data.azurerm_container_registry.existing.login_server
    username             = var.container_registry_username
    password_secret_name = "registry-password"
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
        for_each = local.secret_env_vars
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}
