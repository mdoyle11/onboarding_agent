output "container_app_fqdn" {
  description = "Container App FQDN (use for Teams bot endpoint and webhook URLs)."
  value       = azurerm_container_app.this.ingress[0].fqdn
}

output "container_app_url" {
  description = "Container App HTTPS URL."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "container_registry_login_server" {
  description = "ACR login server (use for docker push)."
  value       = data.azurerm_container_registry.existing.login_server
}

output "storage_account_name" {
  description = "Storage Account used for queue-backed webhook jobs."
  value       = data.azurerm_storage_account.existing.name
}

output "cosmos_account_name" {
  description = "Existing Cosmos DB account used by the app."
  value       = data.azurerm_cosmosdb_account.existing.name
}

output "cosmos_database_name" {
  description = "Cosmos SQL database created for application state."
  value       = azurerm_cosmosdb_sql_database.app.name
}

output "cosmos_state_container_name" {
  description = "Cosmos SQL container used for application state."
  value       = azurerm_cosmosdb_sql_container.state_records.name
}

output "cosmos_conversation_session_container_name" {
  description = "Cosmos SQL container used for ephemeral Teams conversation session metadata."
  value       = azurerm_cosmosdb_sql_container.conversation_sessions.name
}

output "job_queue_name" {
  description = "Azure Storage Queue used for long-running webhook jobs."
  value       = azurerm_storage_queue.jobs.name
}

output "teams_bot_endpoint" {
  description = "Teams bot messaging endpoint."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/api/messages"
}

output "webhook_base_url" {
  description = "Base URL for webhook endpoints."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/webhook"
}
