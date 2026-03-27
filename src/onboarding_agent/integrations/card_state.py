"""Persistent state for Teams onboarding action cards."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

_CARD_STATE_PATH = Path(__file__).resolve().parents[3] / "data" / "card_state.json"
_DOCUSIGN_CARD_STATE_PATH = Path(__file__).resolve().parents[3] / "data" / "docusign_card_state.json"


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            return cast(dict[str, dict[str, Any]], loaded)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read card state file, starting fresh")
    return {}


def _save_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def save_new_hire_card(
    *,
    employee_email: str,
    channel_id: str,
    message_id: str,
    employee_name: str,
    start_date: str,
    department: str,
    location: str,
    manager_email: str,
    summary: str,
) -> None:
    state = _load_state(_CARD_STATE_PATH)
    key = employee_email.strip().lower()
    state[key] = {
        "channel_id": channel_id,
        "message_id": message_id,
        "employee_name": employee_name,
        "employee_email": employee_email,
        "start_date": start_date,
        "department": department,
        "location": location,
        "manager_email": manager_email,
        "summary": summary,
        "email_sent": False,
        "docusign_sent": False,
    }
    _save_state(_CARD_STATE_PATH, state)


def get_new_hire_card(employee_email: str) -> dict[str, Any] | None:
    return _load_state(_CARD_STATE_PATH).get(employee_email.strip().lower())


def mark_new_hire_action_complete(employee_email: str, action: str) -> dict[str, Any] | None:
    state = _load_state(_CARD_STATE_PATH)
    key = employee_email.strip().lower()
    card = state.get(key)
    if card is None:
        return None

    if action == "send_onboarding_email":
        card["email_sent"] = True
    elif action == "send_docusign":
        card["docusign_sent"] = True

    state[key] = card
    _save_state(_CARD_STATE_PATH, state)
    return card


async def refresh_new_hire_card(employee_email: str) -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import new_hire_card
    from onboarding_agent.integrations.teams_proactive import update_proactive_card

    card = get_new_hire_card(employee_email)
    if card is None:
        return {"success": False, "error": f"No stored card state for {employee_email}"}

    updated_card = new_hire_card(
        employee_name=card.get("employee_name", ""),
        employee_email=card.get("employee_email", ""),
        start_date=card.get("start_date", ""),
        department=card.get("department", ""),
        location=card.get("location", ""),
        manager_email=card.get("manager_email", ""),
        summary=card.get("summary", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_sent=bool(card.get("docusign_sent")),
    )
    return await update_proactive_card(
        channel_id=card.get("channel_id", ""),
        message_id=card.get("message_id", ""),
        card=updated_card,
    )


def save_docusign_status_card(
    *,
    employee_email: str,
    channel_id: str,
    message_id: str,
    envelope_id: str,
    status: str,
    summary: str,
) -> None:
    state = _load_state(_DOCUSIGN_CARD_STATE_PATH)
    key = employee_email.strip().lower()
    state[key] = {
        "channel_id": channel_id,
        "message_id": message_id,
        "employee_email": employee_email,
        "envelope_id": envelope_id,
        "status": status,
        "summary": summary,
        "roster_added": False,
        "job_category": "",
    }
    _save_state(_DOCUSIGN_CARD_STATE_PATH, state)


def get_docusign_status_card(employee_email: str) -> dict[str, Any] | None:
    return _load_state(_DOCUSIGN_CARD_STATE_PATH).get(employee_email.strip().lower())


def mark_docusign_roster_complete(employee_email: str, job_category: str) -> dict[str, Any] | None:
    state = _load_state(_DOCUSIGN_CARD_STATE_PATH)
    key = employee_email.strip().lower()
    card = state.get(key)
    if card is None:
        return None

    card["roster_added"] = True
    card["job_category"] = job_category
    state[key] = card
    _save_state(_DOCUSIGN_CARD_STATE_PATH, state)
    return card


async def refresh_docusign_status_card(employee_email: str) -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card
    from onboarding_agent.integrations.teams_proactive import update_proactive_card

    card = get_docusign_status_card(employee_email)
    if card is None:
        return {"success": False, "error": f"No stored DocuSign card state for {employee_email}"}

    updated_card = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
    )
    return await update_proactive_card(
        channel_id=card.get("channel_id", ""),
        message_id=card.get("message_id", ""),
        card=updated_card,
    )
