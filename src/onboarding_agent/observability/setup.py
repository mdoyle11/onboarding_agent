"""OpenTelemetry setup for Azure Monitor and Phoenix exporters."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from onboarding_agent.config import Settings

logger = logging.getLogger(__name__)

_CONFIGURED = False


def configure_observability(settings: Settings) -> None:
    """Configure OpenTelemetry exporters when enabled.

    Exporter imports are optional so local development and tests do not fail when
    observability packages have not been installed yet.
    """
    global _CONFIGURED
    if _CONFIGURED or not settings.observability_enabled:
        return

    _CONFIGURED = True
    _configure_service_metadata(settings)
    _configure_azure_monitor(settings)
    _configure_phoenix(settings)
    _configure_langchain_instrumentation()
    _configure_logging_instrumentation()


def configure_noisy_observability_loggers() -> None:
    """Reduce exporter and SDK success-path log noise while preserving warnings/errors."""
    logging.getLogger("azure.monitor.opentelemetry.exporter.export._base").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.storage.queue").setLevel(logging.WARNING)


def _configure_service_metadata(settings: Settings) -> None:
    resource_attrs = {
        "service.name": settings.otel_service_name,
        "deployment.environment": settings.otel_environment,
    }
    if settings.otel_service_version:
        resource_attrs["service.version"] = settings.otel_service_version
    if settings.phoenix_project_name:
        resource_attrs["openinference.project.name"] = settings.phoenix_project_name
        os.environ.setdefault("PHOENIX_PROJECT_NAME", settings.phoenix_project_name)
    existing = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").strip()
    rendered = ",".join(f"{key}={value}" for key, value in resource_attrs.items() if value)
    os.environ["OTEL_RESOURCE_ATTRIBUTES"] = f"{existing},{rendered}".strip(",") if existing else rendered


def _configure_azure_monitor(settings: Settings) -> None:
    if not settings.azure_monitor_enabled:
        return
    if not settings.azure_monitor_connection_string:
        logger.warning("Azure Monitor observability is enabled but no connection string is configured")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning("azure-monitor-opentelemetry is not installed; Azure Monitor export disabled")
        return

    configure_azure_monitor(
        connection_string=settings.azure_monitor_connection_string,
        logger_name="onboarding_agent",
    )
    logger.info("Azure Monitor OpenTelemetry exporter configured")


def _configure_phoenix(settings: Settings) -> None:
    if not settings.phoenix_enabled:
        return
    if not settings.phoenix_endpoint:
        logger.warning("Phoenix observability is enabled but no endpoint is configured")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError:
        logger.warning("OTLP OpenTelemetry exporter packages are not installed; Phoenix export disabled")
        return

    provider = trace.get_tracer_provider()
    if not hasattr(provider, "add_span_processor"):
        provider = TracerProvider(sampler=TraceIdRatioBased(_bounded_rate(settings.trace_sample_rate)))
        trace.set_tracer_provider(provider)

    headers = _phoenix_headers(settings)

    exporter = OTLPSpanExporter(endpoint=_phoenix_trace_endpoint(settings.phoenix_endpoint), headers=headers or None)
    filtered_exporter = PrefixFilteringSpanExporter(
        exporter,
        prefixes=_parse_prefixes(settings.phoenix_span_name_prefixes),
    )
    provider.add_span_processor(BatchSpanProcessor(filtered_exporter))
    logger.info("Phoenix OTLP exporter configured")


class PrefixFilteringSpanExporter(SpanExporter):
    """Forward only spans with allowed names to a wrapped exporter."""

    def __init__(self, wrapped: SpanExporter, *, prefixes: Sequence[str]) -> None:
        self._wrapped = wrapped
        self._prefixes = tuple(prefix for prefix in prefixes if prefix)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        filtered = [span for span in spans if self._span_allowed(span.name)]
        if not filtered:
            return SpanExportResult.SUCCESS
        return self._wrapped.export(filtered)

    def shutdown(self) -> None:
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._wrapped.force_flush(timeout_millis)

    def _span_allowed(self, name: str) -> bool:
        if not self._prefixes:
            return True
        return name.startswith(self._prefixes)


def _phoenix_headers(settings: Settings) -> dict[str, str]:
    headers = _parse_headers(settings.phoenix_otlp_headers)
    if settings.phoenix_api_key and not _has_header(headers, "authorization"):
        headers["authorization"] = f"Bearer {settings.phoenix_api_key}"
    if settings.phoenix_api_key:
        headers.setdefault("api_key", settings.phoenix_api_key)
    if settings.phoenix_project_name:
        headers.setdefault("project_name", settings.phoenix_project_name)
    return headers


def _phoenix_trace_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip().rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"


def _configure_langchain_instrumentation() -> None:
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
    except ImportError:
        logger.info("openinference-instrumentation-langchain is not installed; LangChain auto-instrumentation disabled")
        return

    LangChainInstrumentor().instrument()
    logger.info("LangChain OpenInference instrumentation configured")


def _configure_logging_instrumentation() -> None:
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
    except ImportError:
        logger.info("opentelemetry-instrumentation-logging is not installed; log correlation disabled")
        return

    LoggingInstrumentor().instrument(set_logging_format=False)


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


def _parse_prefixes(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _has_header(headers: dict[str, str], name: str) -> bool:
    normalized = name.lower()
    return any(key.lower() == normalized for key in headers)


def _bounded_rate(value: Any) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, rate))
