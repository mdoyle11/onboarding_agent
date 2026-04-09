output "container_app_fqdn" {
  description = "Container App FQDN."
  value       = azurerm_container_app.this.ingress[0].fqdn
}

output "container_app_url" {
  description = "Container App HTTPS URL."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "teams_bot_endpoint" {
  description = "Teams bot messaging endpoint managed by the app layer."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/api/messages"
}

output "webhook_base_url" {
  description = "Base URL for webhook endpoints."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/webhook"
}

output "job_queue_name" {
  description = "Azure Storage Queue used for long-running webhook jobs."
  value       = azurerm_storage_queue.jobs.name
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

output "attached_user_assigned_identity_ids" {
  description = "User-assigned identity resource IDs attached to the Container App."
  value       = azurerm_container_app.this.identity[0].identity_ids
}
