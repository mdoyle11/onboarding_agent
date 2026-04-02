"""Persistent state for Teams onboarding action cards."""

from __future__ import annotations

import logging
from typing import Any

from onboarding_agent.domain.identity import identity_key as _card_key
from onboarding_agent.domain.identity import normalize_identity_part
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import TTL_SECONDS_FIELD

logger = logging.getLogger(__name__)

NS_NEW_HIRE = "new_hire_card"
NS_DOCUSIGN = "docusign_card"
_CARD_STATE_TTL_SECONDS = 30 * 24 * 60 * 60


def _store() -> store_mod.StateStore:
    assert store_mod.store is not None, "State store not initialized"
    return store_mod.store


def _card_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        TTL_SECONDS_FIELD: _CARD_STATE_TTL_SECONDS,
    }


async def _resolve_card_key(
    namespace: str,
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> str | None:
    if work_location or job_title or status_change:
        return _card_key(employee_email, work_location, job_title, status_change)

    email_key = normalize_identity_part(employee_email)
    exact_key = _card_key(employee_email)
    exact_card = await _store().get(namespace, exact_key)
    if exact_card is not None:
        return exact_key

    matching_keys = [
        key for key in await _store().list_keys(namespace)
        if key.split("|", 1)[0] == email_key
    ]
    if len(matching_keys) == 1:
        return matching_keys[0]
    return None


async def save_new_hire_card(
    *,
    employee_email: str,
    channel_id: str,
    message_id: str,
    employee_name: str,
    title: str = "",
    status_change: str = "",
    requested_start_date: str = "",
    job_title: str = "",
    work_location: str = "",
    requesting_manager: str = "",
    summary: str = "",
    allow_email_action: bool = True,
    allow_docusign_action: bool = True,
) -> None:
    key = _card_key(employee_email, work_location, job_title, status_change)
    await _store().put(NS_NEW_HIRE, key, _card_record({
        "channel_id": channel_id,
        "message_id": message_id,
        "employee_name": employee_name,
        "employee_email": employee_email,
        "title": title,
        "status_change": status_change,
        "requested_start_date": requested_start_date,
        "job_title": job_title,
        "work_location": work_location,
        "requesting_manager": requesting_manager,
        "summary": summary,
        "email_sent": False,
        "docusign_sent": False,
        "allow_email_action": allow_email_action,
        "allow_docusign_action": allow_docusign_action,
    }))


async def reset_new_hire_card_actions(
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> None:
    """Clear any prior action-complete flags for a fresh test/run."""
    key = await _resolve_card_key(NS_NEW_HIRE, employee_email, work_location, job_title, status_change)
    if key is None:
        return
    card = await _store().get(NS_NEW_HIRE, key)
    if card is None:
        return
    card["email_sent"] = False
    card["docusign_sent"] = False
    await _store().put(NS_NEW_HIRE, key, _card_record(card))


async def get_new_hire_card(
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_NEW_HIRE, employee_email, work_location, job_title, status_change)
    if key is None:
        return None
    return await _store().get(NS_NEW_HIRE, key)


async def mark_new_hire_action_complete(
    employee_email: str,
    action: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_NEW_HIRE, employee_email, work_location, job_title, status_change)
    if key is None:
        return None
    card = await _store().get(NS_NEW_HIRE, key)
    if card is None:
        return None

    if action == "send_onboarding_email":
        card["email_sent"] = True
    elif action == "send_docusign":
        card["docusign_sent"] = True

    await _store().put(NS_NEW_HIRE, key, _card_record(card))
    return card


async def refresh_new_hire_card(
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import new_hire_card
    from onboarding_agent.integrations.teams.proactive import update_proactive_card

    card = await get_new_hire_card(employee_email, work_location, job_title, status_change)
    if card is None:
        return {"success": False, "error": f"No stored card state for {employee_email}"}

    updated_card = new_hire_card(
        employee_name=card.get("employee_name", ""),
        employee_email=card.get("employee_email", ""),
        summary=card.get("summary", ""),
        title=card.get("title", ""),
        status_change=card.get("status_change", ""),
        requested_start_date=card.get("requested_start_date", ""),
        job_title=card.get("job_title", ""),
        work_location=card.get("work_location", ""),
        requesting_manager=card.get("requesting_manager", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_sent=bool(card.get("docusign_sent")),
        allow_email_action=bool(card.get("allow_email_action", True)),
        allow_docusign_action=bool(card.get("allow_docusign_action", True)),
    )
    return await update_proactive_card(
        channel_id=card.get("channel_id", ""),
        message_id=card.get("message_id", ""),
        card=updated_card,
    )


async def save_docusign_status_card(
    *,
    employee_email: str,
    channel_id: str,
    message_id: str,
    envelope_id: str,
    status: str,
    summary: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> None:
    key = _card_key(employee_email, work_location, job_title, status_change)
    await _store().put(NS_DOCUSIGN, key, _card_record({
        "channel_id": channel_id,
        "message_id": message_id,
        "employee_email": employee_email,
        "envelope_id": envelope_id,
        "status": status,
        "summary": summary,
        "work_location": work_location,
        "job_title": job_title,
        "status_change": status_change,
        "roster_added": False,
        "job_category": "",
    }))


async def get_docusign_status_card(
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_DOCUSIGN, employee_email, work_location, job_title, status_change)
    if key is None:
        return None
    return await _store().get(NS_DOCUSIGN, key)


async def mark_docusign_roster_complete(
    employee_email: str,
    job_category: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_DOCUSIGN, employee_email, work_location, job_title, status_change)
    if key is None:
        return None
    card = await _store().get(NS_DOCUSIGN, key)
    if card is None:
        return None

    card["roster_added"] = True
    card["job_category"] = job_category
    await _store().put(NS_DOCUSIGN, key, _card_record(card))
    return card


async def refresh_docusign_status_card(
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card
    from onboarding_agent.integrations.teams.proactive import update_proactive_card

    card = await get_docusign_status_card(employee_email, work_location, job_title, status_change)
    if card is None:
        return {"success": False, "error": f"No stored DocuSign card state for {employee_email}"}

    updated_card = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
        work_location=card.get("work_location", ""),
        job_title=card.get("job_title", ""),
        status_change=card.get("status_change", ""),
    )
    return await update_proactive_card(
        channel_id=card.get("channel_id", ""),
        message_id=card.get("message_id", ""),
        card=updated_card,
    )
