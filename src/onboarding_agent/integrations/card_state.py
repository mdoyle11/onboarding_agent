"""Persistent state for Teams onboarding action cards."""

from __future__ import annotations

import logging
from typing import Any

from onboarding_agent.domain.identity import EmployeeIdentity, normalize_identity_part
from onboarding_agent.domain.identity import identity_key as _card_key
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import TTL_SECONDS_FIELD

logger = logging.getLogger(__name__)

NS_NEW_HIRE = "new_hire_card"
NS_DOCUSIGN = "docusign_card"
_CARD_STATE_TTL_SECONDS = 30 * 24 * 60 * 60


def _submission_card_title(status_change: str) -> str:
    label = str(status_change or "").strip()
    return f"{label or 'Submission'} Requested"


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
    identity: EmployeeIdentity,
    submission_id: str = "",
) -> str | None:
    submission_key = str(submission_id or "").strip()
    if submission_key:
        logger.info(
            "Resolving card key by submission_id: namespace=%s submission_id=%s email=%s location=%s job_title=%s status_change=%s",
            namespace,
            submission_key,
            identity.email or "<missing>",
            identity.work_location or "<missing>",
            identity.job_title or "<missing>",
            identity.status_change or "<missing>",
        )
        for key in await _store().list_keys(namespace):
            card = await _store().get(namespace, key)
            if card is not None and str(card.get("submission_id", "") or "").strip() == submission_key:
                logger.info(
                    "Resolved card key by submission_id: namespace=%s submission_id=%s key=%s message_id=%s",
                    namespace,
                    submission_key,
                    key,
                    str(card.get("message_id", "") or "").strip() or "<missing>",
                )
                return key
        logger.warning(
            "No card state matched submission_id: namespace=%s submission_id=%s email=%s location=%s job_title=%s status_change=%s",
            namespace,
            submission_key,
            identity.email or "<missing>",
            identity.work_location or "<missing>",
            identity.job_title or "<missing>",
            identity.status_change or "<missing>",
        )
        return None

    if identity.work_location or identity.job_title or identity.status_change:
        key = identity.key()
        logger.info(
            "Resolving card key by composite identity: namespace=%s key=%s",
            namespace,
            key,
        )
        return key

    email_key = normalize_identity_part(identity.email)
    exact_key = _card_key(identity.email)
    exact_card = await _store().get(namespace, exact_key)
    if exact_card is not None:
        logger.info(
            "Resolved card key by exact email: namespace=%s key=%s message_id=%s",
            namespace,
            exact_key,
            str(exact_card.get("message_id", "") or "").strip() or "<missing>",
        )
        return exact_key

    matching_keys = [
        key for key in await _store().list_keys(namespace)
        if key.split("|", 1)[0] == email_key
    ]
    if len(matching_keys) == 1:
        logger.info(
            "Resolved card key by single email match: namespace=%s key=%s",
            namespace,
            matching_keys[0],
        )
        return matching_keys[0]
    if matching_keys:
        logger.warning(
            "Ambiguous email-only card lookup: namespace=%s email=%s candidate_keys=%s",
            namespace,
            identity.email or "<missing>",
            matching_keys,
        )
    return None


async def save_new_hire_card(
    *,
    employee_email: str,
    channel_id: str,
    message_id: str,
    submission_id: str = "",
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
        "submission_id": submission_id,
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
        "docusign_draft_created": False,
        "allow_email_action": allow_email_action,
        "allow_docusign_action": allow_docusign_action,
    }))


async def reset_new_hire_card_actions(identity: EmployeeIdentity) -> None:
    """Clear any prior action-complete flags for a fresh test/run."""
    key = await _resolve_card_key(NS_NEW_HIRE, identity)
    if key is None:
        return
    card = await _store().get(NS_NEW_HIRE, key)
    if card is None:
        return
    card["email_sent"] = False
    card["docusign_draft_created"] = False
    await _store().put(NS_NEW_HIRE, key, _card_record(card))


async def get_new_hire_card(identity: EmployeeIdentity, submission_id: str = "") -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_NEW_HIRE, identity, submission_id=submission_id)
    if key is None:
        return None
    return await _store().get(NS_NEW_HIRE, key)


async def _get_card_and_key(
    namespace: str,
    identity: EmployeeIdentity,
    submission_id: str = "",
) -> tuple[str | None, dict[str, Any] | None]:
    key = await _resolve_card_key(namespace, identity, submission_id=submission_id)
    if key is None:
        return None, None
    return key, await _store().get(namespace, key)


async def _refresh_new_hire_card_fields_from_tracker(key: str, card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

    tracker_record = await TrackerClient().find_employee_in_tracker(
        str(card.get("employee_email", "") or ""),
        submission_id=str(card.get("submission_id", "") or ""),
        location=str(card.get("work_location", "") or ""),
        job_title=str(card.get("job_title", "") or ""),
        status_change=str(card.get("status_change", "") or ""),
    )
    if not tracker_record.get("found"):
        return key, card

    refreshed = dict(card)
    refreshed["employee_name"] = str(tracker_record.get("name", "") or refreshed.get("employee_name", "") or "")
    refreshed["requested_start_date"] = str(tracker_record.get("start_date", "") or refreshed.get("requested_start_date", "") or "")
    refreshed["job_title"] = str(tracker_record.get("job_title", "") or refreshed.get("job_title", "") or "")
    refreshed["work_location"] = str(tracker_record.get("location", "") or refreshed.get("work_location", "") or "")
    refreshed["status_change"] = str(tracker_record.get("status_change", "") or refreshed.get("status_change", "") or "")
    refreshed["submission_id"] = str(tracker_record.get("submission_id", "") or refreshed.get("submission_id", "") or "")
    refreshed["title"] = _submission_card_title(refreshed.get("status_change", ""))
    new_key = _card_key(
        refreshed.get("employee_email", ""),
        refreshed.get("work_location", ""),
        refreshed.get("job_title", ""),
        refreshed.get("status_change", ""),
    )
    if new_key != key:
        await _store().delete(NS_NEW_HIRE, key)
    await _store().put(NS_NEW_HIRE, new_key, _card_record(refreshed))
    return new_key, refreshed


async def _refresh_docusign_card_fields_from_tracker(key: str, card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

    tracker_record = await TrackerClient().find_employee_in_tracker(
        str(card.get("employee_email", "") or ""),
        submission_id=str(card.get("submission_id", "") or ""),
        location=str(card.get("work_location", "") or ""),
        job_title=str(card.get("job_title", "") or ""),
        status_change=str(card.get("status_change", "") or ""),
    )
    if not tracker_record.get("found"):
        return key, card

    refreshed = dict(card)
    refreshed["employee_name"] = str(tracker_record.get("name", "") or refreshed.get("employee_name", "") or "")
    refreshed["work_location"] = str(tracker_record.get("location", "") or refreshed.get("work_location", "") or "")
    refreshed["job_title"] = str(tracker_record.get("job_title", "") or refreshed.get("job_title", "") or "")
    refreshed["status_change"] = str(tracker_record.get("status_change", "") or refreshed.get("status_change", "") or "")
    refreshed["submission_id"] = str(tracker_record.get("submission_id", "") or refreshed.get("submission_id", "") or "")
    new_key = _card_key(
        refreshed.get("employee_email", ""),
        refreshed.get("work_location", ""),
        refreshed.get("job_title", ""),
        refreshed.get("status_change", ""),
    )
    if new_key != key:
        await _store().delete(NS_DOCUSIGN, key)
    await _store().put(NS_DOCUSIGN, new_key, _card_record(refreshed))
    return new_key, refreshed


async def mark_new_hire_action_complete(
    identity: EmployeeIdentity,
    action: str,
    submission_id: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_NEW_HIRE, identity, submission_id=submission_id)
    if key is None:
        return None
    card = await _store().get(NS_NEW_HIRE, key)
    if card is None:
        return None

    if action == "send_onboarding_email":
        card["email_sent"] = True
    elif action == "create_docusign_draft":
        card["docusign_draft_created"] = True

    await _store().put(NS_NEW_HIRE, key, _card_record(card))
    return card


async def clear_new_hire_action_complete(
    identity: EmployeeIdentity,
    action: str,
    submission_id: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_NEW_HIRE, identity, submission_id=submission_id)
    if key is None:
        return None
    card = await _store().get(NS_NEW_HIRE, key)
    if card is None:
        return None

    if action == "send_onboarding_email":
        card["email_sent"] = False
    elif action == "create_docusign_draft":
        card["docusign_draft_created"] = False

    await _store().put(NS_NEW_HIRE, key, _card_record(card))
    return card


async def refresh_new_hire_card(identity: EmployeeIdentity, submission_id: str = "") -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import new_hire_card
    from onboarding_agent.integrations.teams.proactive import update_proactive_card

    key, card = await _get_card_and_key(NS_NEW_HIRE, identity, submission_id=submission_id)
    if card is None or key is None:
        return {"success": False, "error": f"No stored card state for {identity.email}"}
    _, card = await _refresh_new_hire_card_fields_from_tracker(key, card)

    updated_card = new_hire_card(
        employee_name=card.get("employee_name", ""),
        employee_email=card.get("employee_email", ""),
        summary=card.get("summary", ""),
        submission_id=card.get("submission_id", ""),
        title=card.get("title", ""),
        status_change=card.get("status_change", ""),
        requested_start_date=card.get("requested_start_date", ""),
        job_title=card.get("job_title", ""),
        work_location=card.get("work_location", ""),
        requesting_manager=card.get("requesting_manager", ""),
        email_sent=bool(card.get("email_sent")),
        docusign_draft_created=bool(card.get("docusign_draft_created")),
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
    employee_name: str = "",
    channel_id: str,
    message_id: str,
    envelope_id: str,
    status: str,
    summary: str,
    submission_id: str = "",
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
    roster_added: bool = False,
    job_category: str = "",
    review_url: str = "",
    allow_send_action: bool = False,
) -> None:
    key = _card_key(employee_email, work_location, job_title, status_change)
    await _store().put(NS_DOCUSIGN, key, _card_record({
        "channel_id": channel_id,
        "message_id": message_id,
        "employee_email": employee_email,
        "employee_name": employee_name,
        "envelope_id": envelope_id,
        "status": status,
        "summary": summary,
        "submission_id": submission_id,
        "work_location": work_location,
        "job_title": job_title,
        "status_change": status_change,
        "roster_added": roster_added,
        "job_category": job_category,
        "review_url": review_url,
        "allow_send_action": allow_send_action,
    }))


async def get_docusign_status_card(identity: EmployeeIdentity, submission_id: str = "") -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_DOCUSIGN, identity, submission_id=submission_id)
    if key is None:
        return None
    return await _store().get(NS_DOCUSIGN, key)


async def delete_docusign_status_card(identity: EmployeeIdentity, submission_id: str = "") -> bool:
    key = await _resolve_card_key(NS_DOCUSIGN, identity, submission_id=submission_id)
    if key is None:
        return False
    await _store().delete(NS_DOCUSIGN, key)
    return True


async def mark_docusign_roster_complete(
    identity: EmployeeIdentity,
    job_category: str,
    submission_id: str = "",
) -> dict[str, Any] | None:
    key = await _resolve_card_key(NS_DOCUSIGN, identity, submission_id=submission_id)
    if key is None:
        return None
    card = await _store().get(NS_DOCUSIGN, key)
    if card is None:
        return None

    card["roster_added"] = True
    card["job_category"] = job_category
    await _store().put(NS_DOCUSIGN, key, _card_record(card))
    return card


async def refresh_docusign_status_card(identity: EmployeeIdentity, submission_id: str = "") -> dict[str, Any]:
    from onboarding_agent.integrations.adaptive_cards import docusign_status_card
    from onboarding_agent.integrations.teams.proactive import update_proactive_card

    key, card = await _get_card_and_key(NS_DOCUSIGN, identity, submission_id=submission_id)
    if card is None or key is None:
        return {"success": False, "error": f"No stored DocuSign card state for {identity.email}"}
    _, card = await _refresh_docusign_card_fields_from_tracker(key, card)

    updated_card = docusign_status_card(
        employee_email=card.get("employee_email", ""),
        envelope_id=card.get("envelope_id", ""),
        status=card.get("status", ""),
        summary=card.get("summary", ""),
        submission_id=card.get("submission_id", ""),
        employee_name=card.get("employee_name", ""),
        roster_added=bool(card.get("roster_added")),
        job_category=card.get("job_category", ""),
        work_location=card.get("work_location", ""),
        job_title=card.get("job_title", ""),
        status_change=card.get("status_change", ""),
        review_url=card.get("review_url", ""),
        allow_send_action=bool(card.get("allow_send_action", False)),
    )
    return await update_proactive_card(
        channel_id=card.get("channel_id", ""),
        message_id=card.get("message_id", ""),
        card=updated_card,
    )
