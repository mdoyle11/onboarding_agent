"""aiohttp application entrypoint."""

from __future__ import annotations

import logging
from typing import cast

from aiohttp import web
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import AgentApplication, Authorization, MemoryStorage, TurnState

from onboarding_agent.agent import runner
from onboarding_agent.config import settings
from onboarding_agent.integrations.teams import proactive as teams_proactive
from onboarding_agent.integrations.teams.bot import register_handlers
from onboarding_agent.integrations.teams.runtime import load_agents_sdk_config
from onboarding_agent.observability.setup import (
    configure_noisy_observability_loggers,
    configure_observability,
)
from onboarding_agent.observability.tracing import start_span
from onboarding_agent.runtime import state_store as store_mod
from onboarding_agent.runtime.job_queue import JobQueue, create_job_queue
from onboarding_agent.runtime.jobs import process_job
from onboarding_agent.runtime.state_store import create_state_store
from onboarding_agent.runtime.webhooks import (
    handle_background_clearance_webhook,
    handle_docusign_webhook,
    handle_new_hire_webhook,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Teams — Agents SDK runtime
# ---------------------------------------------------------------------------

_agent_app: AgentApplication[TurnState] | None = None
_adapter: CloudAdapter | None = None


def _is_synthetic_teams_loadtest(request: web.Request) -> bool:
    return settings.teams_loadtest_mode and request.headers.get("X-Load-Test", "").strip().lower() == "true"


def _setup_teams(app: web.Application) -> None:
    config = load_agents_sdk_config()
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
        synthetic_loadtest = _is_synthetic_teams_loadtest(request)
        with start_span(
            "teams.http_message",
            {
                "http.route": "/api/messages",
                "http.request.content_type": request.content_type,
                "onboarding.synthetic_loadtest": synthetic_loadtest,
            },
        ):
            try:
                response = await adapter.process(request, agent_app)
                if response is None:
                    return web.Response(status=201)
                return cast(web.Response, response)
            except Exception as exc:
                if synthetic_loadtest:
                    logger.warning("Ignoring synthetic Teams load-test reply error: %s", exc)
                    return web.Response(status=201)
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
        store_mod.session_store = create_state_store(
            backend=settings.state_store_backend,
            state_store_dir=settings.state_store_dir,
            cosmos_endpoint=settings.cosmos_endpoint,
            cosmos_key=settings.cosmos_key,
            cosmos_database_name=settings.cosmos_database_name,
            cosmos_container_name=settings.conversation_session_cosmos_container_name,
        )
        logger.info("Initializing agent…")
        await runner.initialize()
        logger.info("Initializing job queue (%s)…", settings.job_queue_backend)
        app["job_queue"] = create_job_queue(
            backend=settings.job_queue_backend,
            handler=process_job,
            managed_identity_client_id=settings.managed_identity_client_id,
            azure_storage_queue_account_url=settings.azure_storage_queue_account_url,
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
    configure_observability(settings)
    configure_noisy_observability_loggers()
    logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)
    logging.getLogger("azure.cosmos._cosmos_http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    app = create_app()
    web.run_app(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
