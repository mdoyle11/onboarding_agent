"""Shared MCP tool client factories."""

from __future__ import annotations

from onboarding_agent.integrations.docusign_client import DocuSignClient
from onboarding_agent.integrations.outlook_email_client import OutlookEmailClient
from onboarding_agent.integrations.teams.messenger import TeamsMessenger
from onboarding_agent.integrations.workbook.separations_client import SeparationsClient
from onboarding_agent.integrations.workbook.staff_roster_client import StaffRosterClient
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient


def tracker() -> TrackerClient:
    return TrackerClient()


def staff_roster() -> StaffRosterClient:
    return StaffRosterClient()


def separations() -> SeparationsClient:
    return SeparationsClient()


def docusign() -> DocuSignClient:
    return DocuSignClient()


def messenger() -> TeamsMessenger:
    return TeamsMessenger()


def email_client() -> OutlookEmailClient:
    """Return the Outlook email client."""
    return OutlookEmailClient()
