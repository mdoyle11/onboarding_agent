output "resource_group_name" {
  description = "Resource group name for the environment."
  value       = azurerm_resource_group.this.name
}

output "location" {
  description = "Azure region for the environment."
  value       = azurerm_resource_group.this.location
}

output "container_registry_id" {
  description = "Container Registry resource ID."
  value       = azurerm_container_registry.this.id
}

output "container_registry_name" {
  description = "Container Registry name."
  value       = azurerm_container_registry.this.name
}

output "container_registry_login_server" {
  description = "Container Registry login server."
  value       = azurerm_container_registry.this.login_server
}

output "container_app_environment_id" {
  description = "Container Apps environment resource ID."
  value       = azurerm_container_app_environment.this.id
}

output "container_app_environment_name" {
  description = "Container Apps environment name."
  value       = azurerm_container_app_environment.this.name
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace resource ID."
  value       = azurerm_log_analytics_workspace.this.id
}

output "storage_account_id" {
  description = "Storage account resource ID."
  value       = azurerm_storage_account.this.id
}

output "storage_account_name" {
  description = "Storage account name."
  value       = azurerm_storage_account.this.name
}

output "storage_account_primary_connection_string" {
  description = "Storage account connection string for bootstrap use."
  value       = azurerm_storage_account.this.primary_connection_string
  sensitive   = true
}

output "cosmos_account_id" {
  description = "Cosmos DB account resource ID."
  value       = azurerm_cosmosdb_account.this.id
}

output "cosmos_account_name" {
  description = "Cosmos DB account name."
  value       = azurerm_cosmosdb_account.this.name
}

output "cosmos_endpoint" {
  description = "Cosmos DB endpoint."
  value       = azurerm_cosmosdb_account.this.endpoint
}

output "cosmos_primary_key" {
  description = "Cosmos DB primary key for bootstrap use."
  value       = azurerm_cosmosdb_account.this.primary_key
  sensitive   = true
}

output "key_vault_id" {
  description = "Key Vault resource ID."
  value       = azurerm_key_vault.this.id
}

output "key_vault_name" {
  description = "Key Vault name."
  value       = azurerm_key_vault.this.name
}

output "key_vault_uri" {
  description = "Key Vault URI."
  value       = azurerm_key_vault.this.vault_uri
}

output "key_vault_secret_names" {
  description = "Key Vault secret names seeded by foundation."
  value       = keys(azurerm_key_vault_secret.seeded)
  sensitive   = true
}

output "shared_user_assigned_identity_id" {
  description = "Shared user-assigned managed identity resource ID."
  value       = azurerm_user_assigned_identity.shared.id
}

output "shared_user_assigned_identity_client_id" {
  description = "Shared user-assigned managed identity client ID."
  value       = azurerm_user_assigned_identity.shared.client_id
}

output "shared_user_assigned_identity_principal_id" {
  description = "Shared user-assigned managed identity principal ID."
  value       = azurerm_user_assigned_identity.shared.principal_id
}

output "azure_openai_account_id" {
  description = "Azure OpenAI account resource ID."
  value       = azurerm_cognitive_account.azure_openai.id
}

output "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint."
  value       = azurerm_cognitive_account.azure_openai.endpoint
}

output "azure_openai_deployment_name" {
  description = "Azure OpenAI model deployment name."
  value       = var.azure_openai_deployment_name
}

output "azure_bot_id" {
  description = "Azure Bot resource ID."
  value       = azapi_resource.azure_bot.id
}

output "azure_bot_name" {
  description = "Azure Bot name."
  value       = var.azure_bot_name
}

output "microsoft_app_id" {
  description = "Bot client ID consumed by the app layer."
  value       = var.microsoft_app_id
}
