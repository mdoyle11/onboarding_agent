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

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace resource ID from foundation."
  type        = string
}

variable "application_insights_connection_string" {
  description = "Application Insights connection string from foundation."
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

variable "queue_poll_interval_seconds" {
  description = "Polling interval for the Azure Storage Queue worker. Increase to reduce background dependency telemetry."
  type        = number
  default     = 15
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

variable "observability_enabled" {
  description = "Enable OpenTelemetry setup in the application."
  type        = bool
  default     = false
}

variable "otel_service_name" {
  description = "OpenTelemetry service name."
  type        = string
  default     = "onboarding-agent"
}

variable "azure_monitor_enabled" {
  description = "Enable Azure Monitor OpenTelemetry export in the application."
  type        = bool
  default     = false
}

variable "phoenix_enabled" {
  description = "Enable Phoenix OpenTelemetry export in the application."
  type        = bool
  default     = false
}

variable "phoenix_endpoint" {
  description = "Phoenix OTLP HTTP traces endpoint."
  type        = string
  default     = ""
}

variable "phoenix_api_key" {
  description = "Phoenix API key. Stored as a Container App secret when provided."
  type        = string
  sensitive   = true
  default     = ""
}

variable "phoenix_project_name" {
  description = "Phoenix project name used for agent traces."
  type        = string
  default     = "onboarding-agent-prod"
}

variable "phoenix_otlp_headers" {
  description = "Additional comma-separated OTLP headers for Phoenix export."
  type        = string
  default     = ""
}

variable "phoenix_span_name_prefixes" {
  description = "Comma-separated span name prefixes exported to Phoenix. Azure Monitor still receives full telemetry."
  type        = string
  default     = "teams.,agent.,tracker.,graph.excel.tracker."
}

variable "trace_sample_rate" {
  description = "OpenTelemetry trace sampling rate from 0.0 to 1.0."
  type        = number
  default     = 1.0
}

variable "trace_capture_full_payloads" {
  description = "Allow raw prompt/tool payload capture. Keep false in production."
  type        = bool
  default     = false
}

variable "trace_hash_salt" {
  description = "Secret salt used to hash identifiers in traces. Stored as a Container App secret when provided."
  type        = string
  sensitive   = true
  default     = ""
}

variable "evals_enabled" {
  description = "Enable sampled online deterministic agent evals."
  type        = bool
  default     = false
}

variable "eval_sample_rate" {
  description = "Online eval sampling rate from 0.0 to 1.0."
  type        = number
  default     = 0.05
}

variable "azure_monitor_alerts_enabled" {
  description = "Create Azure Monitor scheduled query alerts for baseline app observability."
  type        = bool
  default     = false
}

variable "azure_monitor_action_group_name" {
  description = "Azure Monitor action group name for onboarding-agent alerts."
  type        = string
  default     = "ag-onboarding-agent"
}

variable "azure_monitor_action_group_short_name" {
  description = "Short name for the Azure Monitor action group."
  type        = string
  default     = "onboardops"
}

variable "azure_monitor_alert_email_receivers" {
  description = "Map of alert receiver names to email addresses."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Optional custom tags."
  type        = map(string)
  default     = {}
}
