locals {
  base_tags = merge(
    {
      project     = var.project_name
      environment = var.environment
      managed_by  = "terraform"
      layer       = "foundation"
    },
    var.tags
  )
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.base_tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = var.log_analytics_workspace_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_in_days
  tags                = local.base_tags
}

resource "azurerm_container_registry" "this" {
  name                = var.container_registry_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.base_tags
}

resource "azurerm_storage_account" "this" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = local.base_tags
}

resource "azurerm_cosmosdb_account" "this" {
  name                          = var.cosmos_account_name
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  free_tier_enabled             = var.cosmos_free_tier_enabled
  public_network_access_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.this.location
    failover_priority = 0
  }

  tags = local.base_tags
}

resource "azurerm_key_vault" "this" {
  name                          = var.key_vault_name
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  tenant_id                     = var.microsoft_app_tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = false
  public_network_access_enabled = true
  tags                          = local.base_tags
}

resource "azurerm_user_assigned_identity" "shared" {
  name                = var.shared_user_assigned_identity_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.base_tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = var.container_app_environment_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.base_tags
}

resource "azurerm_cognitive_account" "azure_openai" {
  name                          = var.azure_openai_account_name
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  kind                          = "OpenAI"
  sku_name                      = var.azure_openai_sku_name
  public_network_access_enabled = true
  custom_subdomain_name         = var.azure_openai_account_name
  tags                          = local.base_tags
}

resource "azapi_resource" "azure_openai_deployment" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2023-05-01"
  name      = var.azure_openai_deployment_name
  parent_id = azurerm_cognitive_account.azure_openai.id

  body = jsonencode({
    sku = {
      name     = var.azure_openai_deployment_sku_name
      capacity = var.azure_openai_deployment_capacity
    }
    properties = {
      model = {
        format  = "OpenAI"
        name    = var.azure_openai_model_name
        version = var.azure_openai_model_version
      }
    }
  })
}

resource "azurerm_role_assignment" "shared_identity_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.shared.principal_id
}

resource "azurerm_role_assignment" "shared_identity_key_vault_secrets_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.shared.principal_id
}

resource "azurerm_role_assignment" "current_principal_key_vault_secrets_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "shared_identity_azure_openai_user" {
  scope                = azurerm_cognitive_account.azure_openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.shared.principal_id
}

resource "azurerm_role_assignment" "shared_identity_storage_queue_data_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_user_assigned_identity.shared.principal_id
}

resource "azurerm_key_vault_secret" "seeded" {
  for_each = nonsensitive(toset(keys(var.key_vault_secrets)))

  name         = each.value
  value        = var.key_vault_secrets[each.value]
  key_vault_id = azurerm_key_vault.this.id
  content_type = "text/plain"

  depends_on = [
    azurerm_role_assignment.shared_identity_key_vault_secrets_user,
    azurerm_role_assignment.current_principal_key_vault_secrets_officer,
  ]
}

resource "azapi_resource" "azure_bot" {
  type      = "Microsoft.BotService/botServices@2023-09-15-preview"
  name      = var.azure_bot_name
  parent_id = azurerm_resource_group.this.id
  location  = "global"
  tags      = local.base_tags

  body = jsonencode({
    kind = "azurebot"
    sku = {
      name = var.azure_bot_sku_name
    }
    properties = {
      displayName         = var.azure_bot_display_name
      endpoint            = var.bot_initial_endpoint
      msaAppId            = var.microsoft_app_id
      msaAppTenantId      = var.microsoft_app_tenant_id
      msaAppType          = var.azure_bot_msa_app_type
      publicNetworkAccess = "Enabled"
      tenantId            = var.microsoft_app_tenant_id
    }
  })
}

resource "azapi_resource" "azure_bot_teams_channel" {
  type      = "Microsoft.BotService/botServices/channels@2023-09-15-preview"
  name      = "MsTeamsChannel"
  parent_id = azapi_resource.azure_bot.id
  location  = "global"

  body = jsonencode({
    properties = {
      channelName = "MsTeamsChannel"
      properties = {
        acceptedTerms = true
        isEnabled     = true
      }
    }
  })
}
