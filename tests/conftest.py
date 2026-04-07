"""Shared pytest fixtures."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_docusign_client():
    """Return a mock DocuSignClient with async methods pre-configured."""
    with patch("onboarding_agent.integrations.docusign_client.DocuSignClient") as mock_cls:
        instance = AsyncMock()
        mock_cls.return_value = instance
        yield instance
