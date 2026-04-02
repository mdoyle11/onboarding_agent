"""Microsoft Graph authentication helpers."""

from __future__ import annotations

from azure.identity.aio import ClientSecretCredential

from onboarding_agent.config import settings

_SCOPES = ["https://graph.microsoft.com/.default"]


async def graph_access_token() -> str:
    """Acquire a Microsoft Graph access token using the configured service principal."""
    cred = ClientSecretCredential(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    try:
        token = await cred.get_token(*_SCOPES)
        return token.token
    finally:
        await cred.close()
