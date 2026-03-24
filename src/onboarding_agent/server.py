"""aiohttp application — hosts /api/messages (Teams) and /webhook/new-hire (Power Automate).

Chat interface is selected via CHAT_INTERFACE env var:
  - "teams" (default): Bot Framework adapter on POST /api/messages
  - "slack": Socket Mode handler started alongside the aiohttp server
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any

from aiohttp import web
from langchain_core.messages import HumanMessage

from onboarding_agent.agent import graph as graph_module
from onboarding_agent.agent.state import default_state
from onboarding_agent.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook handler (shared — no chat interface dependency)
# ---------------------------------------------------------------------------

def _notification_channel() -> str:
    return settings.notification_channel()


def _webhook_prompt(state: dict[str, Any]) -> str:
    interface = "Slack" if settings.is_slack() else "Teams"
    notification_tool = "send_slack_channel_notification" if settings.is_slack() else "send_teams_channel_notification"
    return (
        f"A new hire has been submitted via Microsoft Forms. "
        f"Employee: {state['employee_name']} ({state['employee_email']}), "
        f"Start date: {state['employee_start_date']}, "
        f"Department: {state['employee_department']}, "
        f"Location: {state['employee_location']}, "
        f"Manager: {state['employee_manager_email']}. "
        "Please run the onboarding pipeline: "
        "1) Check if employee is already in the tracker; if not, add them. "
        "2) Check if a DocuSign draft already exists; if not, create one (draft only — do NOT send it). "
        "3) Draft the onboarding welcome email using draft_onboarding_email (draft only — do NOT send it). "
        f"4) Send a {interface} channel notification using {notification_tool} "
        f"to channel '{_notification_channel()}' summarising what was done: the DocuSign draft "
        "and onboarding email draft are ready for HR to review. HR must explicitly approve sending each."
    )


async def handle_new_hire_webhook(request: web.Request) -> web.Response:
    """POST /webhook/new-hire — Power Automate form submission webhook."""
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided_secret, settings.webhook_secret):
        logger.warning("Webhook rejected: invalid secret")
        return web.Response(status=401, text="Unauthorized")

    try:
        payload: dict[str, Any] = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    logger.info("New-hire webhook received: %s", payload.get("employeeEmail", "unknown"))

    state = default_state()
    state["trigger_source"] = "pa_webhook"
    state["employee_email"] = payload.get("employeeEmail", "")
    state["employee_name"] = payload.get("employeeName", "")
    state["employee_start_date"] = payload.get("startDate", "")
    state["employee_department"] = payload.get("department", "")
    state["employee_location"] = payload.get("location", "")
    state["employee_manager_email"] = payload.get("managerEmail", "")
    state["forms_submission_id"] = payload.get("submissionId", "")
    state["forms_data_raw"] = payload
    state["teams_channel_id"] = _notification_channel()
    state["messages"] = [HumanMessage(content=_webhook_prompt(state))]

    compiled = graph_module.compiled_graph
    if compiled is None:
        return web.Response(status=503, text="Agent not ready")

    config = {"configurable": {"thread_id": state["employee_email"] or "webhook"}}
    try:
        await compiled.ainvoke(state, config)
        return web.Response(status=200, text="Onboarding pipeline triggered")
    except Exception as exc:
        logger.exception("Webhook graph invocation failed")
        return web.Response(status=500, text=str(exc))


# ---------------------------------------------------------------------------
# DocuSign Connect webhook (envelope status callbacks)
# ---------------------------------------------------------------------------

def _docusign_prompt(envelope_id: str, status: str, employee_email: str) -> str:
    interface = "Slack" if settings.is_slack() else "Teams"
    notification_tool = "send_slack_channel_notification" if settings.is_slack() else "send_teams_channel_notification"
    return (
        f"DocuSign envelope {envelope_id} for {employee_email} has changed to status: {status}. "
        f"1) If the status is 'completed', call update_tracker_stage with "
        f'stage="Offer Letter Signed" for {employee_email}. '
        f"2) If the status is 'sent', call update_tracker_stage with "
        f'stage="Sent Offer Letter" for {employee_email}. '
        f"3) Send a {interface} channel notification using {notification_tool} "
        f"to channel '{_notification_channel()}' summarising the DocuSign status change."
    )


def _parse_docusign_xml(body: bytes) -> dict[str, str]:
    """Extract envelope_id, status, and employee_email from DocuSign Connect XML."""
    import xml.etree.ElementTree as ET

    ns = {"ds": "http://www.docusign.net/API/3.0"}
    root = ET.fromstring(body)

    # EnvelopeStatus is the main container
    env_status_el = root.find(".//ds:EnvelopeStatus", ns)
    if env_status_el is None:
        # Try without namespace (some payloads omit it)
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

        # Custom fields
        for field in env_status_el.findall(".//ds:CustomField", ns) or env_status_el.findall(".//CustomField"):
            name_el = field.find("ds:Name", ns) or field.find("Name")
            val_el = field.find("ds:Value", ns) or field.find("Value")
            if name_el is not None and (name_el.text or "") == "employee_email":
                employee_email = (val_el.text or "") if val_el is not None else ""
                break

    return {"envelope_id": envelope_id, "status": status, "employee_email": employee_email}


def _parse_docusign_json(payload: dict[str, Any]) -> dict[str, str]:
    """Extract envelope_id, status, and employee_email from DocuSign Connect JSON."""
    envelope_id = payload.get("envelopeId", "")
    status = payload.get("status", "")
    employee_email = ""

    custom_fields = payload.get("customFields", {})
    for field in custom_fields.get("textCustomFields", []):
        if field.get("name") == "employee_email":
            employee_email = field.get("value", "")
            break

    return {"envelope_id": envelope_id, "status": status, "employee_email": employee_email}


async def handle_docusign_webhook(request: web.Request) -> web.Response:
    """POST /webhook/docusign — DocuSign Connect envelope status callback."""
    body = await request.read()
    content_type = request.content_type or ""

    logger.info("DocuSign webhook received: content_type=%s body_len=%d", content_type, len(body))

    try:
        if "xml" in content_type or body.lstrip().startswith(b"<"):
            parsed = _parse_docusign_xml(body)
        else:
            payload = json.loads(body)
            parsed = _parse_docusign_json(payload)
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

    compiled = graph_module.compiled_graph
    if compiled is None:
        return web.Response(status=503, text="Agent not ready")

    state = default_state()
    state["trigger_source"] = "pa_webhook"
    state["employee_email"] = employee_email
    state["docusign_envelope_id"] = envelope_id
    state["docusign_envelope_status"] = envelope_status
    state["teams_channel_id"] = _notification_channel()
    state["messages"] = [HumanMessage(content=_docusign_prompt(envelope_id, envelope_status, employee_email))]

    config = {"configurable": {"thread_id": f"docusign-{envelope_id}"}}
    try:
        asyncio.create_task(compiled.ainvoke(state, config))
        return web.Response(status=200, text="Acknowledged")
    except Exception as exc:
        logger.exception("DocuSign webhook graph invocation failed")
        return web.Response(status=500, text=str(exc))


# ---------------------------------------------------------------------------
# Teams — Bot Framework adapter (only when CHAT_INTERFACE=teams)
# ---------------------------------------------------------------------------

def _setup_teams(app: web.Application) -> None:
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
    from botbuilder.schema import Activity
    from onboarding_agent.integrations.teams_bot import OnboardingBot

    adapter = BotFrameworkAdapter(
        BotFrameworkAdapterSettings(
            app_id=settings.microsoft_app_id,
            app_password=settings.microsoft_app_password,
        )
    )
    bot = OnboardingBot()

    async def on_error(context: Any, error: Exception) -> None:
        logger.exception("Bot adapter error: %s", error)

    adapter.on_turn_error = on_error  # type: ignore[assignment]

    async def handle_messages(request: web.Request) -> web.Response:
        """POST /api/messages — Bot Framework Teams messages."""
        if "application/json" not in request.content_type:
            return web.Response(status=415)
        body = await request.json()
        activity = Activity().deserialize(body)
        auth_header = request.headers.get("Authorization", "")
        try:
            await adapter.process_activity(activity, auth_header, bot.on_turn)
            return web.Response(status=200)
        except Exception as exc:
            logger.exception("Error processing Teams activity")
            return web.Response(status=500, text=str(exc))

    app.router.add_post("/api/messages", handle_messages)
    logger.info("Teams Bot Framework adapter registered on POST /api/messages")


# ---------------------------------------------------------------------------
# Slack — Socket Mode (only when CHAT_INTERFACE=slack)
# ---------------------------------------------------------------------------

def _setup_slack(app: web.Application) -> None:
    # Handler must be created inside the running event loop — defer to on_startup.
    async def start_socket_mode(application: web.Application) -> None:
        from onboarding_agent.integrations.slack_bot import create_slack_handler
        handler = create_slack_handler()
        application["slack_handler"] = handler
        logger.info("Starting Slack Socket Mode handler…")
        asyncio.create_task(handler.start_async())

    async def stop_socket_mode(application: web.Application) -> None:
        handler = application.get("slack_handler")
        if handler:
            await handler.close_async()

    app.on_startup.append(start_socket_mode)
    app.on_cleanup.append(stop_socket_mode)
    logger.info("Slack Socket Mode will start on server startup")


# ---------------------------------------------------------------------------
# App factory + startup
# ---------------------------------------------------------------------------

async def _on_startup(app: web.Application) -> None:
    logger.info("Building LangGraph agent…")
    graph_module.compiled_graph = await graph_module.build_graph()
    logger.info("Agent ready — chat interface: %s", settings.chat_interface)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/new-hire", handle_new_hire_webhook)
    app.router.add_post("/webhook/docusign", handle_docusign_webhook)
    app.on_startup.append(_on_startup)

    if settings.is_slack():
        _setup_slack(app)
    else:
        _setup_teams(app)

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    app = create_app()
    web.run_app(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
