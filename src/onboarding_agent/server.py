"""aiohttp application entrypoint."""

from __future__ import annotations

import logging
import os
from typing import cast

from aiohttp import web
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import AgentApplication, Authorization, MemoryStorage, TurnState

from onboarding_agent.agent import graph as graph_module
from onboarding_agent.runtime.checkpointing import close_checkpointer
from onboarding_agent.runtime.job_queue import JobQueue, create_job_queue
from onboarding_agent.runtime.jobs import process_job
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.state_store import create_state_store
from onboarding_agent.runtime.webhooks import (
    handle_background_clearance_webhook,
    handle_docusign_webhook,
    handle_new_hire_webhook,
)
from onboarding_agent.config import settings
from onboarding_agent.integrations import teams_proactive
from onboarding_agent.integrations.teams_bot import register_handlers

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Teams — Agents SDK runtime
# ---------------------------------------------------------------------------

_agent_app: AgentApplication[TurnState] | None = None
_adapter: CloudAdapter | None = None


def _ensure_agents_sdk_env() -> None:
    has_service_connection = bool(
        settings.microsoft_app_id and settings.microsoft_app_password and settings.azure_tenant_id
    )
    if has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID",
            settings.microsoft_app_id,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET",
            settings.microsoft_app_password,
        )
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID",
            settings.azure_tenant_id,
        )
    if settings.microsoft_app_allow_anonymous or not has_service_connection:
        os.environ.setdefault(
            "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__ANONYMOUS_ALLOWED",
            "true",
        )
    os.environ.setdefault("PORT", str(settings.port))


def _setup_teams(app: web.Application) -> None:
    _ensure_agents_sdk_env()

    config = load_configuration_from_env(os.environ)
    storage = MemoryStorage()
    connection_manager = MsalConnectionManager(**config)
    adapter = CloudAdapter(connection_manager=connection_manager)
    authorization = Authorization(storage, connection_manager, **config)
    agent_app = AgentApplication[TurnState](
        storage=storage,
        adapter=adapter,
        authorization=authorization,
        **config,
    )
    register_handlers(agent_app)
    teams_proactive.adapter = adapter
    teams_proactive.bot_app_id = settings.microsoft_app_id

    global _agent_app, _adapter
    _agent_app = agent_app
    _adapter = adapter

    async def handle_messages(request: web.Request) -> web.Response:
        """POST /api/messages — Microsoft 365 Agents SDK endpoint for Teams/App Tester."""
        if "application/json" not in request.content_type:
            return web.Response(status=415)
        try:
            response = await adapter.process(request, agent_app)
            if response is None:
                return web.Response(status=201)
            return cast(web.Response, response)
        except Exception as exc:
            logger.exception("Error processing Teams activity")
            return web.Response(status=500, text=str(exc))

    async def handle_messages_probe(_request: web.Request) -> web.Response:
        return web.Response(status=200, text="ok")

    app.router.add_get("/api/messages", handle_messages_probe)
    app.router.add_post("/api/messages", handle_messages)
    logger.info("Teams Agents SDK endpoint registered on /api/messages")


# ---------------------------------------------------------------------------
# App factory + startup
# ---------------------------------------------------------------------------

async def _on_startup(app: web.Application) -> None:
    try:
        logger.info("Initializing state store (%s)…", settings.state_store_backend)
        store_mod.store = create_state_store(
            backend=settings.state_store_backend,
            state_store_dir=settings.state_store_dir,
            cosmos_endpoint=settings.cosmos_endpoint,
            cosmos_key=settings.cosmos_key,
            cosmos_database_name=settings.cosmos_database_name,
            cosmos_container_name=settings.cosmos_container_name,
        )
        logger.info("Building LangGraph agent…")
        graph_module.compiled_graph = await graph_module.build_graph()
        logger.info("Initializing job queue (%s)…", settings.job_queue_backend)
        app["job_queue"] = create_job_queue(
            backend=settings.job_queue_backend,
            handler=process_job,
            azure_storage_queue_connection_string=settings.azure_storage_queue_connection_string,
            azure_storage_queue_name=settings.azure_storage_queue_name,
            queue_poll_interval_seconds=settings.queue_poll_interval_seconds,
        )
        await cast(JobQueue, app["job_queue"]).start()
        logger.info("Agent ready — Teams interface active")
    except Exception:
        logger.exception("Application startup failed")
        raise


async def _on_cleanup(app: web.Application) -> None:
    job_queue = app.get("job_queue")
    if job_queue is not None:
        await cast(JobQueue, job_queue).close()
    await close_checkpointer()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/new-hire", handle_new_hire_webhook)
    app.router.add_post("/webhook/docusign", handle_docusign_webhook)
    app.router.add_post("/webhook/background-clearance", handle_background_clearance_webhook)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    _setup_teams(app)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)
    logging.getLogger("azure.cosmos._cosmos_http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    app = create_app()
    web.run_app(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
