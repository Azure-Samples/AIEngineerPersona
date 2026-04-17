"""
telemetry.py — OpenTelemetry bootstrap for the story-generation backend.

Uses Agent Framework's built-in ``configure_otel_providers()`` to set up
the TracerProvider, exporters, and Agent Framework instrumentation from
environment variables.  Also auto-instruments FastAPI so every incoming
HTTP request gets its own trace span automatically.

See: https://learn.microsoft.com/en-us/agent-framework/agents/observability
"""

import logging
from typing import Any

from agent_framework.observability import configure_otel_providers
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import Span

from .config import settings

logger = logging.getLogger(__name__)

# Max bytes of body to record as a span attribute (avoids giant attribute values).
_BODY_CAPTURE_LIMIT = 4096


def _response_hook(span: Span, scope: dict[str, Any], message: dict[str, Any]) -> None:
    """Record the response body on each ASGI http.send span.

    Fires for every outgoing ASGI message — captures the raw bytes from
    'http.response.body' events (i.e. each SSE chunk) and attaches them
    as a span attribute so the content is visible in AI Toolkit.
    """
    if not span or not span.is_recording():
        return
    body: bytes = message.get("body", b"")
    if body:
        span.set_attribute(
            "http.response.body",
            body[:_BODY_CAPTURE_LIMIT].decode("utf-8", errors="replace"),
        )


def configure_telemetry(app: FastAPI) -> None:
    """Set up OTEL providers via Agent Framework and instrument FastAPI.

    This must be called **before** any agent-framework imports that create
    workflows or executors, so the framework can pick up the active
    TracerProvider and emit its own spans.

    Does nothing if ``settings.otel_enabled`` is False.
    """
    if not settings.otel_enabled:
        logger.info("OpenTelemetry is disabled (OTEL_ENABLED=false)")
        return

    # 1. Configure OTEL providers — reads OTEL_EXPORTER_OTLP_ENDPOINT,
    #    OTEL_SERVICE_NAME, ENABLE_INSTRUMENTATION, and ENABLE_SENSITIVE_DATA
    #    from environment variables automatically.
    configure_otel_providers()

    # 2. Auto-instrument FastAPI (creates a parent span for every HTTP request).
    #    client_response_hook fires for every outgoing ASGI message, letting us
    #    capture the SSE event body on each "http send" span.
    FastAPIInstrumentor.instrument_app(app, client_response_hook=_response_hook)

    logger.info("OpenTelemetry configured via Agent Framework")
