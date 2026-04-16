"""Tests for observability exporter setup helpers."""

import os

from onboarding_agent.config import Settings
from onboarding_agent.observability.setup import (
    PrefixFilteringSpanExporter,
    _configure_service_metadata,
    _parse_prefixes,
    _phoenix_headers,
    _phoenix_trace_endpoint,
)


def test_phoenix_headers_use_bearer_auth_from_api_key() -> None:
    settings = Settings(
        docusign_account_id="docu",
        docusign_integration_key="integration",
        docusign_user_id="user",
        docusign_template_id="template",
        webhook_secret="secret",
        phoenix_api_key="phoenix-key",
        phoenix_project_name="project",
    )

    result = _phoenix_headers(settings)

    assert result["authorization"] == "Bearer phoenix-key"
    assert result["api_key"] == "phoenix-key"
    assert result["project_name"] == "project"


def test_phoenix_headers_do_not_override_explicit_authorization() -> None:
    settings = Settings(
        docusign_account_id="docu",
        docusign_integration_key="integration",
        docusign_user_id="user",
        docusign_template_id="template",
        webhook_secret="secret",
        phoenix_api_key="phoenix-key",
        phoenix_project_name="project",
        phoenix_otlp_headers="authorization=Bearer explicit",
    )

    result = _phoenix_headers(settings)

    assert result["authorization"] == "Bearer explicit"


def test_phoenix_trace_endpoint_appends_otlp_path_to_collector_base() -> None:
    assert (
        _phoenix_trace_endpoint("https://app.phoenix.arize.com/s/bpa-agents")
        == "https://app.phoenix.arize.com/s/bpa-agents/v1/traces"
    )


def test_phoenix_trace_endpoint_preserves_explicit_trace_path() -> None:
    assert (
        _phoenix_trace_endpoint("https://app.phoenix.arize.com/s/bpa-agents/v1/traces")
        == "https://app.phoenix.arize.com/s/bpa-agents/v1/traces"
    )


def test_service_metadata_sets_openinference_project_resource_attribute(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    settings = Settings(
        docusign_account_id="docu",
        docusign_integration_key="integration",
        docusign_user_id="user",
        docusign_template_id="template",
        webhook_secret="secret",
        otel_service_name="onboarding-agent",
        otel_environment="prod",
        phoenix_project_name="onboarding-agent-prod",
    )

    _configure_service_metadata(settings)

    attrs = os.environ["OTEL_RESOURCE_ATTRIBUTES"]
    assert "service.name=onboarding-agent" in attrs
    assert "deployment.environment=prod" in attrs
    assert "openinference.project.name=onboarding-agent-prod" in attrs
    assert os.environ["PHOENIX_PROJECT_NAME"] == "onboarding-agent-prod"


def test_parse_prefixes_trims_empty_values() -> None:
    assert _parse_prefixes("teams., agent.,,") == ("teams.", "agent.")


def test_prefix_filtering_exporter_only_forwards_allowed_spans() -> None:
    class WrappedExporter:
        def __init__(self) -> None:
            self.exported: list[object] = []
            self.flushed = False
            self.shutdown_called = False

        def export(self, spans):
            self.exported.extend(spans)
            return 0

        def force_flush(self, timeout_millis=30000):
            self.flushed = True
            return True

        def shutdown(self):
            self.shutdown_called = True

    class Span:
        def __init__(self, name: str) -> None:
            self.name = name

    wrapped = WrappedExporter()
    exporter = PrefixFilteringSpanExporter(wrapped, prefixes=("teams.", "agent."))

    result = exporter.export(
        [
            Span("QueueClient.receive_messages"),
            Span("teams.http_message"),
            Span("agent.tool.get_onboarding_status"),
        ]
    )

    assert result == 0
    assert [span.name for span in wrapped.exported] == [
        "teams.http_message",
        "agent.tool.get_onboarding_status",
    ]
