"""aiohttp application — hosts /api/messages (Teams) and /webhook/new-hire (Power Automate)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity
from langchain_core.messages import HumanMessage

from onboarding_agent import agent as agent_pkg
from onboarding_agent.agent import graph as graph_module
from onboarding_agent.agent.state import default_state
from onboarding_agent.config import settings
from onboarding_agent.integrations.teams_bot import OnboardingBot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot Framework adapter
# ---------------------------------------------------------------------------
_adapter_settings = BotFrameworkAdapterSettings(
    app_id=settings.microsoft_app_id,
    app_password=settings.microsoft_app_password,
)
_adapter = BotFrameworkAdapter(_adapter_settings)
_bot = OnboardingBot()


async def on_error(context: Any, error: Exception) -> None:
    logger.exception("Bot adapter error: %s", error)


_adapter.on_turn_error = on_error  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_messages(request: web.Request) -> web.Response:
    """POST /api/messages — Bot Framework Teams messages."""
    if "application/json" not in request.content_type:
        return web.Response(status=415)

    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    try:
        await _adapter.process_activity(activity, auth_header, _bot.on_turn)
        return web.Response(status=200)
    except Exception as exc:
        logger.exception("Error processing Teams activity")
        return web.Response(status=500, text=str(exc))


async def handle_new_hire_webhook(request: web.Request) -> web.Response:
    """POST /webhook/new-hire — Power Automate form submission webhook."""
    # Verify shared secret
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided_secret, settings.webhook_secret):
        logger.warning("Webhook rejected: invalid secret")
        return web.Response(status=401, text="Unauthorized")

    try:
        payload: dict[str, Any] = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    logger.info("New-hire webhook received: %s", payload.get("employeeEmail", "unknown"))

    # Pre-populate OnboardingState from Power Automate payload
    state = default_state()
    state["trigger_source"] = "pa_webhook"
    state["employee_email"] = payload.get("employeeEmail", "")
    state["employee_name"] = payload.get("employeeName", "")
    state["employee_start_date"] = payload.get("startDate", "")
    state["employee_department"] = payload.get("department", "")
    state["employee_manager_email"] = payload.get("managerEmail", "")
    state["forms_submission_id"] = payload.get("submissionId", "")
    state["forms_data_raw"] = payload
    state["teams_channel_id"] = settings.teams_channel_id
    state["messages"] = [
        HumanMessage(
            content=(
                f"A new hire has been submitted via Microsoft Forms. "
                f"Employee: {state['employee_name']} ({state['employee_email']}), "
                f"Start date: {state['employee_start_date']}, "
                f"Department: {state['employee_department']}, "
                f"Manager: {state['employee_manager_email']}. "
                "Please run the full onboarding pipeline: "
                "1) Check if employee is already in the tracker; if not, add them. "
                "2) Check if a DocuSign draft already exists; if not, create one. "
                "3) Send a Teams channel notification summarising what was done."
            )
        )
    ]

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
# App factory + startup
# ---------------------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    logger.info("Building LangGraph agent…")
    graph_module.compiled_graph = await graph_module.build_graph()
    logger.info("Agent ready")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/messages", handle_messages)
    app.router.add_post("/webhook/new-hire", handle_new_hire_webhook)
    app.on_startup.append(on_startup)
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
