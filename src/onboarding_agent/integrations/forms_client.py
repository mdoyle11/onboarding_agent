"""Microsoft Forms client via Microsoft Graph."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from onboarding_agent.config import settings
from onboarding_agent.integrations.graph.auth import graph_access_token

logger = logging.getLogger(__name__)


class FormsClient:
    """Fetch Microsoft Forms responses through Graph."""

    async def get_submission_by_id(self, submission_id: str) -> dict[str, Any]:
        """Fetch a specific Forms response."""
        try:
            token = await graph_access_token()
            url = (
                f"https://graph.microsoft.com/v1.0/forms/{settings.graph_forms_form_id}"
                f"/responses/{submission_id}"
            )
            async with aiohttp.ClientSession() as session, session.get(
                url, headers={"Authorization": f"Bearer {token}"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"found": True, "data": data}
                return {"found": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("get_submission_by_id failed")
            return {"found": False, "error": str(exc)}
