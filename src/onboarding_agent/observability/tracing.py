"""Small wrappers around OpenTelemetry for app-specific trace attributes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from onboarding_agent.config import settings
from onboarding_agent.observability.pii import safe_attributes


def tracer() -> trace.Tracer:
    return trace.get_tracer("onboarding_agent")


def set_span_attributes(span: trace.Span, attrs: Mapping[str, Any]) -> None:
    safe = safe_attributes(
        attrs,
        salt=settings.trace_hash_salt,
        capture_full_payloads=settings.trace_capture_full_payloads,
    )
    for key, value in safe.items():
        if value is not None:
            span.set_attribute(key, value)


def add_span_event(span: trace.Span, name: str, attrs: Mapping[str, Any] | None = None) -> None:
    """Add a sanitized event to a span."""
    span.add_event(
        name,
        safe_attributes(
            attrs or {},
            salt=settings.trace_hash_salt,
            capture_full_payloads=settings.trace_capture_full_payloads,
        ),
    )


@contextmanager
def start_span(
    name: str,
    attrs: Mapping[str, Any] | None = None,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[trace.Span]:
    """Start a span and automatically record exceptions without leaking raw attrs."""
    with tracer().start_as_current_span(name, kind=kind) as span:
        if attrs:
            set_span_attributes(span, attrs)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return ""
    return f"{span_context.trace_id:032x}"
