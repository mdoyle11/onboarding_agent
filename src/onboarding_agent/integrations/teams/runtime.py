"""Shared Teams Agents SDK environment/bootstrap helpers."""

from __future__ import annotations

import os
from typing import Any, cast

from microsoft_agents.activity import load_configuration_from_env

from onboarding_agent.config import settings


def ensure_agents_sdk_env() -> None:
    """Populate required Teams Agents SDK environment variables from settings."""
    has_service_connection = bool(
        settings.microsoft_app_id and settings.microsoft_app_password and settings.azure_tenant_id
    )
    if has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID",
            settings.microsoft_app_id,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET",
            settings.microsoft_app_password,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID",
            settings.azure_tenant_id,
        )
    if settings.microsoft_app_allow_anonymous or not has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__ANONYMOUS_ALLOWED",
            "true",
        )
    os.environ.setdefault("PORT", str(settings.port))


def load_agents_sdk_config() -> dict[str, Any]:
    """Load Teams Agents SDK configuration after ensuring env variables are populated."""
    ensure_agents_sdk_env()
    return cast(dict[str, Any], load_configuration_from_env(os.environ))
