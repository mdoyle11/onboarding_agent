"""Shared pytest fixtures."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_graph_client():
    """Return a mock GraphClient with async methods pre-configured."""
    with patch("onboarding_agent.integrations.graph_client.GraphClient") as mock_cls:
        instance = AsyncMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture()
def mock_docusign_client():
    """Return a mock DocuSignClient with async methods pre-configured."""
    with patch("onboarding_agent.integrations.docusign_client.DocuSignClient") as mock_cls:
        instance = AsyncMock()
        mock_cls.return_value = instance
        yield instance
