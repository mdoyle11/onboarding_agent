variable "project_name" {
  description = "Logical project name used for naming."
  type        = string
  default     = "onboarding-agent"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group name created by the foundation layer."
  type        = string
}

variable "container_app_environment_id" {
  description = "Container Apps environment resource ID from foundation."
  type        = string
}

variable "container_registry_name" {
  description = "Azure Container Registry name from foundation."
  type        = string
}

variable "key_vault_name" {
  description = "Key Vault name from foundation."
  type        = string
}

variable "storage_account_name" {
  description = "Storage account name from foundation."
  type        = string
}

variable "cosmos_account_name" {
  description = "Cosmos account name from foundation."
  type        = string
}

variable "azure_bot_resource_id" {
  description = "Azure Bot resource ID from foundation."
  type        = string
}

variable "shared_user_assigned_identity_id" {
  description = "Shared user-assigned managed identity resource ID from foundation."
  type        = string
}

variable "shared_user_assigned_identity_client_id" {
  description = "Shared user-assigned managed identity client ID from foundation."
  type        = string
  default     = ""
}

variable "key_vault_secret_names" {
  description = "Key Vault secret names used by the app layer."
  type        = map(string)
  default = {
    webhook_secret         = "webhook-secret"
    microsoft_app_password = "microsoft-app-password"
    azure_client_secret    = "azure-client-secret"
    docusign_private_key   = "docusign-private-key"
  }
}

variable "container_app_name" {
  description = "Container App name."
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

variable "llm_provider" {
  description = "LLM provider to use (anthropic, gemini, or azure_openai)."
  type        = string
  default     = "gemini"
}

variable "gemini_model" {
  description = "Gemini model name used when llm_provider is gemini."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint from foundation."
  type        = string
  default     = ""
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version."
  type        = string
  default     = "2024-10-21"
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI model deployment name."
  type        = string
  default     = ""
}

variable "microsoft_app_id" {
  description = "Microsoft App ID for Teams bot."
  type        = string
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
  description = "Azure tenant ID."
  type        = string
}

variable "azure_client_id" {
  description = "Existing Graph app registration client ID."
  type        = string
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
  description = "Optional Excel table name for onboarding tracker reads."
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
  description = "DocuSign user ID for JWT grant."
  type        = string
}

variable "docusign_template_id" {
  description = "DocuSign envelope template ID."
  type        = string
}

variable "docusign_connect_url" {
  description = "Base URL used by DocuSign Connect callbacks."
  type        = string
  default     = ""
}

variable "cosmos_key" {
  description = "Cosmos account key from foundation. Replace later with identity-based access."
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
  description = "Default TTL in seconds for Teams conversation session metadata."
  type        = number
  default     = 259200
}

variable "storage_account_connection_string" {
  description = "Storage account connection string from foundation. Replace later with identity-based access."
  type        = string
  sensitive   = true
  default     = ""
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

variable "staff_roster_default_separations_sheet_name" {
  description = "Default staff roster separations worksheet name."
  type        = string
  default     = "Separations"
}

variable "staff_roster_locations_json" {
  description = "Serialized staff roster workbook mapping payload."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Optional custom tags."
  type        = map(string)
  default     = {}
}
