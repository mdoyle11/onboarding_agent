"""Webhook parsing and validation helpers."""

from __future__ import annotations

import hmac
import json
import logging
import time
from typing import Any, cast

from aiohttp import web

from onboarding_agent.config import settings
from onboarding_agent.runtime.job_queue import JobQueue
from onboarding_agent.runtime.jobs import JOB_BACKGROUND_CLEARANCE, JOB_DOCUSIGN, JOB_NEW_HIRE

logger = logging.getLogger(__name__)


def _accepted_response() -> web.Response:
    """Return a small explicit JSON response for webhook callers."""
    return web.json_response({"ok": True, "status": "accepted"}, status=200)


def is_valid_webhook_secret(provided_secret: str, expected_secret: str) -> bool:
    """Return whether the provided shared secret matches the configured one."""
    return hmac.compare_digest(provided_secret, expected_secret)


def parse_json_payload(body: bytes) -> dict[str, Any]:
    """Parse a JSON payload from raw request bytes."""
    return dict(json.loads(body))


def parse_docusign_payload(body: bytes, content_type: str) -> dict[str, str]:
    """Extract envelope_id, status, and employee_email from DocuSign payloads."""
    if "xml" in content_type or body.lstrip().startswith(b"<"):
        return _parse_docusign_xml(body)
    return _parse_docusign_json(parse_json_payload(body))


def _parse_docusign_xml(body: bytes) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    ns = {"ds": "http://www.docusign.net/API/3.0"}
    root = ET.fromstring(body)

    env_status_el = root.find(".//ds:EnvelopeStatus", ns)
    if env_status_el is None:
        env_status_el = root.find(".//EnvelopeStatus")

    envelope_id = ""
    status = ""
    employee_email = ""

    if env_status_el is not None:
        eid = env_status_el.find("ds:EnvelopeID", ns)
        if eid is None:
            eid = env_status_el.find("EnvelopeID")
        envelope_id = (eid.text or "") if eid is not None else ""

        st = env_status_el.find("ds:Status", ns)
        if st is None:
            st = env_status_el.find("Status")
        status = (st.text or "") if st is not None else ""

        fields = env_status_el.findall(".//ds:CustomField", ns) or env_status_el.findall(".//CustomField")
        for field in fields:
            name_el = field.find("ds:Name", ns)
            if name_el is None:
                name_el = field.find("Name")
            val_el = field.find("ds:Value", ns)
            if val_el is None:
                val_el = field.find("Value")
            if name_el is not None and (name_el.text or "") == "employee_email":
                employee_email = (val_el.text or "") if val_el is not None else ""
                break

    return {"envelope_id": envelope_id, "status": status, "employee_email": employee_email}


def _parse_docusign_json(payload: dict[str, Any]) -> dict[str, str]:
    envelope_id = str(payload.get("envelopeId", ""))
    status = str(payload.get("status", ""))
    employee_email = ""

    custom_fields = payload.get("customFields", {})
    for field in custom_fields.get("textCustomFields", []):
        if field.get("name") == "employee_email":
            employee_email = str(field.get("value", ""))
            break

    return {"envelope_id": envelope_id, "status": status, "employee_email": employee_email}


def _job_queue(request: web.Request) -> JobQueue:
    return cast(JobQueue, request.app["job_queue"])


async def handle_new_hire_webhook(request: web.Request) -> web.Response:
    """POST /webhook/new-hire — Power Automate form submission webhook."""
    started = time.perf_counter()
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if not is_valid_webhook_secret(provided_secret, settings.webhook_secret):
        logger.warning("Webhook rejected: invalid secret")
        return web.Response(status=401, text="Unauthorized")

    try:
        payload = parse_json_payload(await request.read())
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    employee_email = str(payload.get("staffEmail", "unknown"))
    logger.info("New-hire webhook received: %s", employee_email)
    await _job_queue(request).enqueue(JOB_NEW_HIRE, payload)
    logger.info(
        "New-hire webhook queued for %s in %.3fs",
        employee_email,
        time.perf_counter() - started,
    )
    return _accepted_response()


async def handle_docusign_webhook(request: web.Request) -> web.Response:
    """POST /webhook/docusign — DocuSign Connect envelope status callback."""
    started = time.perf_counter()
    body = await request.read()
    content_type = request.content_type or ""

    logger.info("DocuSign webhook received: content_type=%s body_len=%d", content_type, len(body))

    try:
        parsed = parse_docusign_payload(body, content_type)
    except Exception as exc:
        logger.exception("Failed to parse DocuSign webhook payload")
        return web.Response(status=400, text=f"Parse error: {exc}")

    envelope_id = parsed["envelope_id"]
    envelope_status = parsed["status"]
    employee_email = parsed["employee_email"]

    logger.info(
        "DocuSign webhook: envelope=%s status=%s email=%s",
        envelope_id[:8] if envelope_id else "?",
        envelope_status,
        employee_email,
    )

    if not envelope_id or not envelope_status:
        return web.Response(status=200, text="Ignored — missing envelope data")

    try:
        await _job_queue(request).enqueue(
            JOB_DOCUSIGN,
            {
                "envelope_id": envelope_id,
                "status": envelope_status,
                "employee_email": employee_email,
            },
        )
        return _accepted_response()
    except Exception as exc:
        logger.exception("DocuSign webhook queue enqueue failed")
        return web.Response(status=500, text=str(exc))
    finally:
        logger.info(
            "DocuSign webhook completed for %s in %.3fs",
            envelope_id[:8] if envelope_id else "?",
            time.perf_counter() - started,
        )


async def handle_background_clearance_webhook(request: web.Request) -> web.Response:
    """POST /webhook/background-clearance — Power Automate background clearance form callback."""
    started = time.perf_counter()
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if not is_valid_webhook_secret(provided_secret, settings.webhook_secret):
        logger.warning("Background clearance webhook rejected: invalid secret")
        return web.Response(status=401, text="Unauthorized")

    try:
        payload = parse_json_payload(await request.read())
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    employee_email = str(payload.get("employeeEmail", ""))
    logger.info("Background clearance webhook received: %s", employee_email or "unknown")

    try:
        await _job_queue(request).enqueue(JOB_BACKGROUND_CLEARANCE, payload)
        return _accepted_response()
    except Exception as exc:
        logger.exception("Background clearance webhook queue enqueue failed")
        return web.Response(status=500, text=str(exc))
    finally:
        logger.info(
            "Background clearance webhook completed for %s in %.3fs",
            employee_email or "unknown",
            time.perf_counter() - started,
        )
