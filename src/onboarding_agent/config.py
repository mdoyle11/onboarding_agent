"""Application configuration — validated at startup via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str

    # Azure AD
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str

    # Microsoft Graph — Excel tracker
    graph_excel_drive_id: str
    graph_excel_item_id: str
    graph_excel_sheet_name: str = "Onboarding"

    # Microsoft Graph — Forms
    graph_forms_form_id: str

    # Teams
    teams_team_id: str
    teams_channel_id: str

    # DocuSign (JWT Grant)
    docusign_account_id: str
    docusign_integration_key: str
    docusign_user_id: str
    docusign_private_key_path: str
    docusign_template_id: str
    docusign_base_url: str = "https://demo.docusign.net/restapi"

    # Azure Bot
    microsoft_app_id: str
    microsoft_app_password: str

    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # Webhook security
    webhook_secret: str


# Module-level singleton — imported everywhere
settings = Settings()  # type: ignore[call-arg]
