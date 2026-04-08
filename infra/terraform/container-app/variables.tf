variable "project_name" {
  description = "Logical project name used for naming."
  type        = string
  default     = "onboarding-agent"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "resource_group_name" {
  description = "Existing Azure resource group name used for this deployment."
  type        = string
}

variable "container_registry_name" {
  description = "Existing Azure Container Registry name."
  type        = string
}

variable "container_registry_username" {
  description = "Username for the existing Azure Container Registry. Requires ACR admin user to be enabled."
  type        = string
}

variable "container_registry_password" {
  description = "Password for the existing Azure Container Registry. Requires ACR admin user to be enabled."
  type        = string
  sensitive   = true
}

variable "container_app_environment_name" {
  description = "Container Apps environment name."
  type        = string
}

variable "container_app_name" {
  description = "Container App name."
  type        = string
}

variable "storage_account_name" {
  description = "Existing Azure Storage Account name used for queue-backed job processing."
  type        = string
}

variable "existing_cosmos_account_name" {
  description = "Existing Azure Cosmos DB account name."
  type        = string
}

variable "image_tag" {
  description = "Container image tag."
  type        = string
  default     = "latest"
}

variable "min_replicas" {
  description = "Minimum container replicas."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum container replicas."
  type        = number
  default     = 3
}

variable "cpu" {
  description = "CPU allocation for the container."
  type        = number
  default     = 0.5
}

variable "memory" {
  description = "Memory allocation for the container."
  type        = string
  default     = "1Gi"
}

# ---------------------------------------------------------------------------
# Application secrets (passed as Container App secrets)
# ---------------------------------------------------------------------------

variable "anthropic_api_key" {
  description = "Anthropic API key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Gemini API key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "llm_provider" {
  description = "LLM provider to use (anthropic or gemini)."
  type        = string
  default     = "gemini"
}

variable "gemini_model" {
  description = "Gemini model name used when llm_provider is gemini."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "webhook_secret" {
  description = "HMAC secret for webhook validation."
  type        = string
  sensitive   = true
}

variable "microsoft_app_id" {
  description = "Microsoft App ID for Teams bot."
  type        = string
}

variable "microsoft_app_password" {
  description = "Microsoft App password for Teams bot."
  type        = string
  sensitive   = true
}

variable "microsoft_app_allow_anonymous" {
  description = "Allow anonymous Teams/App Tester traffic in non-production environments."
  type        = bool
  default     = false
}

variable "teams_loadtest_mode" {
  description = "Enable non-production synthetic Teams load-test handling."
  type        = bool
  default     = false
}

variable "azure_tenant_id" {
  description = "Azure AD tenant ID."
  type        = string
}

variable "azure_client_id" {
  description = "Azure AD client ID for Graph API."
  type        = string
}

variable "azure_client_secret" {
  description = "Azure AD client secret for Graph API."
  type        = string
  sensitive   = true
}

variable "graph_excel_drive_id" {
  description = "SharePoint drive ID for the onboarding Excel tracker."
  type        = string
}

variable "graph_excel_item_id" {
  description = "File item ID for the onboarding Excel tracker."
  type        = string
}

variable "graph_excel_table_name" {
  description = "Optional Excel table name for onboarding tracker reads. Falls back to usedRange when empty."
  type        = string
  default     = ""
}

variable "docusign_account_id" {
  description = "DocuSign account ID."
  type        = string
}

variable "docusign_integration_key" {
  description = "DocuSign integration key (client ID)."
  type        = string
}

variable "docusign_user_id" {
  description = "DocuSign user ID for JWT Grant."
  type        = string
}

variable "docusign_private_key" {
  description = "DocuSign RSA private key (inline PEM content)."
  type        = string
  sensitive   = true
}

variable "docusign_template_id" {
  description = "DocuSign envelope template ID."
  type        = string
}

variable "docusign_connect_url" {
  description = "Base URL used by DocuSign Connect callbacks, for example https://your-app.azurecontainerapps.io."
  type        = string
  default     = ""
}

variable "cosmos_key" {
  description = "Key for the existing Cosmos DB account."
  type        = string
  sensitive   = true
}

variable "cosmos_database_name" {
  description = "Cosmos database name for application state."
  type        = string
  default     = "onboarding-agent"
}

variable "state_store_backend" {
  description = "Application state store backend (file or cosmos)."
  type        = string
  default     = "cosmos"
}

variable "cosmos_state_container_name" {
  description = "Cosmos container name for application state."
  type        = string
  default     = "state-records"
}

variable "conversation_session_cosmos_container_name" {
  description = "Cosmos container name for ephemeral Teams conversation session metadata."
  type        = string
  default     = "conversation-sessions"
}

variable "conversation_session_cosmos_default_ttl" {
  description = "Default TTL in seconds for Teams conversation session metadata. Use -1 to disable automatic expiry."
  type        = number
  default     = 259200
}

variable "azure_storage_queue_name" {
  description = "Azure Storage Queue name for long-running webhook jobs."
  type        = string
  default     = "onboarding-jobs"
}

variable "teams_channel_id" {
  description = "Default Teams channel ID for notifications."
  type        = string
  default     = ""
}

variable "outlook_sender_email" {
  description = "Outlook sender email address."
  type        = string
  default     = ""
}

variable "staff_roster_locations_json" {
  description = "JSON string mapping locations to staff roster workbook IDs."
  type        = string
  sensitive   = true
  default     = "{}"
}

variable "staff_roster_default_separations_sheet_name" {
  description = "Default separations sheet name for all staff roster workbooks."
  type        = string
  default     = "Separations"
}

variable "storage_account_connection_string" {
  description = "Connection string for the existing Azure Storage Account."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
