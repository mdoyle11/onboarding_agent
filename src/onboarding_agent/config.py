"""Application configuration — validated at startup via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------------------------------------------------------------------------
    # LLM provider — "gemini" | "anthropic"
    # ---------------------------------------------------------------------------
    llm_provider: str = "anthropic"

    # Anthropic (required when llm_provider=anthropic)
    anthropic_api_key: str = ""

    # Gemini (required when llm_provider=gemini)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ---------------------------------------------------------------------------
    # Teams / Agents SDK
    # ---------------------------------------------------------------------------
    teams_team_id: str = ""
    teams_channel_id: str = ""

    microsoft_app_id: str = ""
    microsoft_app_password: str = ""
    microsoft_app_allow_anonymous: bool = False

    # ---------------------------------------------------------------------------
    # Microsoft Graph — Excel tracker
    # ---------------------------------------------------------------------------
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    graph_excel_drive_id: str = ""
    graph_excel_item_id: str = ""
    graph_excel_sheet_name: str = "Onboarding"

    # Microsoft Graph — Forms (optional)
    graph_forms_form_id: str = ""

    # ---------------------------------------------------------------------------
    # DocuSign (JWT Grant — server-to-server)
    # ---------------------------------------------------------------------------
    docusign_account_id: str
    docusign_integration_key: str
    docusign_user_id: str
    docusign_private_key_path: str
    docusign_template_id: str
    docusign_base_url: str = "https://demo.docusign.net/restapi"
    docusign_connect_url: str = ""  # ngrok URL for DocuSign Connect callbacks

    # ---------------------------------------------------------------------------
    # Outlook email
    # ---------------------------------------------------------------------------
    outlook_sender_email: str = ""

    # Email template
    email_template_path: str = "templates/onboarding_email.html"
    email_subject_template: str = "Welcome to the team, $employee_name!"

    # ---------------------------------------------------------------------------
    # Server
    # ---------------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    webhook_secret: str

    # ---------------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------------
    def is_gemini(self) -> bool:
        return self.llm_provider.lower() == "gemini"

    def notification_channel(self) -> str:
        """Return the configured Teams notification channel ID."""
        return self.teams_channel_id


# Module-level singleton — imported everywhere
settings = Settings()  # type: ignore[call-arg]
