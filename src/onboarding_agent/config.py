"""Application configuration — validated at startup via pydantic-settings."""

from __future__ import annotations

import json
from pathlib import Path

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

    # Microsoft Graph — Staff Roster workbooks (one workbook per location)
    # JSON shape:
    # {
    #   "collier": {
    #     "drive_id": "...",
    #     "item_id": "...",
    #     "roster_sheet_name": "Roster_Data",
    #     "capacity_sheet_name": "Capacity"
    #   }
    # }
    staff_roster_locations_file: str = ""
    staff_roster_locations_json: str = "{}"
    staff_roster_default_sheet_name: str = "Roster_Data"
    staff_roster_default_capacity_sheet_name: str = "Capacity"

    # Microsoft Graph — Forms (optional)
    graph_forms_form_id: str = ""

    # ---------------------------------------------------------------------------
    # DocuSign (JWT Grant — server-to-server)
    # ---------------------------------------------------------------------------
    docusign_account_id: str
    docusign_integration_key: str
    docusign_user_id: str
    docusign_private_key_path: str = ""
    docusign_private_key: str = ""
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
    # State store — "file" | "cosmos"
    # ---------------------------------------------------------------------------
    state_store_backend: str = "file"
    state_store_dir: str = "data"
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database_name: str = "onboarding-agent"
    cosmos_container_name: str = "state-records"

    # ---------------------------------------------------------------------------
    # Job queue — "local" | "azure"
    # ---------------------------------------------------------------------------
    job_queue_backend: str = "local"
    azure_storage_queue_connection_string: str = ""
    azure_storage_queue_name: str = "onboarding-jobs"
    queue_poll_interval_seconds: float = 1.0

    # ---------------------------------------------------------------------------
    # LangGraph checkpointing — "memory" | "cosmos"
    # ---------------------------------------------------------------------------
    graph_checkpoint_backend: str = "memory"
    graph_checkpoint_cosmos_database_name: str = "onboarding-agent"
    graph_checkpoint_cosmos_container_name: str = "langgraph-checkpoints"

    # ---------------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------------
    def is_gemini(self) -> bool:
        return self.llm_provider.lower() == "gemini"

    def docusign_private_key_bytes(self) -> bytes:
        """Return the DocuSign private key as bytes.

        Prefers inline secret (env var) over file path, since file paths
        don't work well in containerized deployments.
        """
        if self.docusign_private_key:
            normalized = self.docusign_private_key.replace("\\n", "\n").strip()
            if not normalized.endswith("\n"):
                normalized = f"{normalized}\n"
            return normalized.encode("utf-8")
        if self.docusign_private_key_path:
            return Path(self.docusign_private_key_path).read_bytes()
        raise ValueError("DocuSign private key is not configured")

    def notification_channel(self) -> str:
        """Return the configured Teams notification channel ID."""
        return self.teams_channel_id

    def staff_roster_locations(self) -> dict[str, dict[str, str]]:
        """Return location-keyed workbook config for staff rosters."""
        parsed = self._load_staff_roster_raw_config()
        if not isinstance(parsed, dict):
            return {}

        normalized: dict[str, dict[str, str]] = {}
        for raw_key, raw_value in parsed.items():
            if not isinstance(raw_key, str) or not isinstance(raw_value, dict):
                continue
            key = self._normalize_location_key(raw_key)
            value = {
                "drive_id": str(raw_value.get("drive_id", self.graph_excel_drive_id) or self.graph_excel_drive_id),
                "item_id": str(raw_value.get("item_id", "") or ""),
                "roster_sheet_name": str(
                    raw_value.get("roster_sheet_name", self.staff_roster_default_sheet_name) or self.staff_roster_default_sheet_name
                ),
                "capacity_sheet_name": str(
                    raw_value.get("capacity_sheet_name", self.staff_roster_default_capacity_sheet_name)
                    or self.staff_roster_default_capacity_sheet_name
                ),
            }
            normalized[key] = value
        return normalized

    def _load_staff_roster_raw_config(self) -> object:
        if self.staff_roster_locations_file:
            path = Path(self.staff_roster_locations_file)
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        try:
            return json.loads(self.staff_roster_locations_json or "{}")
        except json.JSONDecodeError:
            return {}

    def staff_roster_workbook(self, location: str) -> dict[str, str] | None:
        """Resolve a location name to its staff roster workbook config."""
        key = self._normalize_location_key(location)
        if not key:
            return None
        return self.staff_roster_locations().get(key)

    @staticmethod
    def _normalize_location_key(location: str) -> str:
        return "".join(ch.lower() for ch in location.strip() if ch.isalnum())


# Module-level singleton — imported everywhere
settings = Settings()  # type: ignore[call-arg]
