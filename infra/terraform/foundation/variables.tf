variable "project_name" {
  description = "Logical project name used for naming."
  type        = string
  default     = "onboarding-agent"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "location" {
  description = "Azure region for regional resources."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group name for the new environment."
  type        = string
}

variable "container_registry_name" {
  description = "Azure Container Registry name."
  type        = string
}

variable "container_app_environment_name" {
  description = "Container Apps environment name."
  type        = string
}

variable "log_analytics_workspace_name" {
  description = "Log Analytics workspace name."
  type        = string
}

variable "application_insights_name" {
  description = "Application Insights resource name for app telemetry."
  type        = string
}

variable "storage_account_name" {
  description = "Storage account name used for queues and other app storage."
  type        = string
}

variable "cosmos_account_name" {
  description = "Cosmos DB account name."
  type        = string
}

variable "cosmos_free_tier_enabled" {
  description = "Enable Cosmos DB free tier for this environment."
  type        = bool
  default     = false
}

variable "key_vault_name" {
  description = "Key Vault name for application secrets."
  type        = string
}

variable "azure_openai_account_name" {
  description = "Azure OpenAI / Azure AI account name."
  type        = string
}

variable "shared_user_assigned_identity_name" {
  description = "User-assigned managed identity name shared across app-layer workloads."
  type        = string
}

variable "azure_openai_sku_name" {
  description = "SKU name for the Azure OpenAI account."
  type        = string
  default     = "S0"
}

variable "azure_openai_deployment_name" {
  description = "Azure OpenAI model deployment name consumed by the app layer."
  type        = string
}

variable "azure_openai_model_name" {
  description = "Azure OpenAI model name to deploy."
  type        = string
}

variable "azure_openai_model_version" {
  description = "Azure OpenAI model version to deploy."
  type        = string
}

variable "azure_openai_deployment_sku_name" {
  description = "Azure OpenAI deployment SKU name."
  type        = string
  default     = "Standard"
}

variable "azure_openai_deployment_capacity" {
  description = "Azure OpenAI deployment capacity. Interpreted by Azure based on deployment SKU."
  type        = number
  default     = 1
}

variable "key_vault_secrets" {
  description = "Secrets to seed into Key Vault for the environment. Keep real values in tfvars, not in git."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "azure_bot_name" {
  description = "Azure Bot resource name."
  type        = string
}

variable "azure_bot_display_name" {
  description = "Display name shown for the Azure Bot."
  type        = string
  default     = "Onboarding Agent"
}

variable "azure_bot_sku_name" {
  description = "Azure Bot SKU."
  type        = string
  default     = "F0"
}

variable "microsoft_app_id" {
  description = "Existing approved Entra application client ID used by the Teams bot."
  type        = string
}

variable "microsoft_app_tenant_id" {
  description = "Tenant ID for the existing bot app registration."
  type        = string
}

variable "azure_bot_msa_app_type" {
  description = "Bot app type. SingleTenant is the expected production default."
  type        = string
  default     = "SingleTenant"
}

variable "bot_initial_endpoint" {
  description = "Placeholder endpoint used when foundation creates the bot. The app layer will later overwrite this."
  type        = string
  default     = "https://placeholder.invalid/api/messages"
}

variable "log_retention_in_days" {
  description = "Log Analytics retention in days."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Optional custom tags."
  type        = map(string)
  default     = {}
}
