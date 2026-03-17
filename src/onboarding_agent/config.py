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
    # Chat interface — "slack" | "teams"
    # ---------------------------------------------------------------------------
    chat_interface: str = "teams"

    # Slack (required when chat_interface=slack)
    slack_bot_token: str = ""       # xoxb-...
    slack_app_token: str = ""       # xapp-... (Socket Mode)
    slack_channel_id: str = ""      # default HR notification channel

    # Teams (required when chat_interface=teams)
    teams_team_id: str = ""
    teams_channel_id: str = ""

    # Azure Bot (required when chat_interface=teams)
    microsoft_app_id: str = ""
    microsoft_app_password: str = ""

    # ---------------------------------------------------------------------------
    # Tracker backend — "sheets" | "excel"
    # ---------------------------------------------------------------------------
    tracker_backend: str = "excel"

    # Google Sheets (required when tracker_backend=sheets)
    google_service_account_path: str = ""   # path to service account JSON key
    google_sheets_id: str = ""              # ID from the Google Sheets URL
    google_sheets_tab: str = "Onboarding"  # worksheet tab name

    # Microsoft Graph — Excel (required when tracker_backend=excel)
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

    # ---------------------------------------------------------------------------
    # Server
    # ---------------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    webhook_secret: str

    # ---------------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------------
    def is_slack(self) -> bool:
        return self.chat_interface.lower() == "slack"

    def is_teams(self) -> bool:
        return self.chat_interface.lower() == "teams"

    def is_gemini(self) -> bool:
        return self.llm_provider.lower() == "gemini"

    def is_sheets(self) -> bool:
        return self.tracker_backend.lower() == "sheets"

    def notification_channel(self) -> str:
        """Return the configured notification channel ID for the active interface."""
        return self.slack_channel_id if self.is_slack() else self.teams_channel_id


# Module-level singleton — imported everywhere
settings = Settings()  # type: ignore[call-arg]
