"""
telemetry.py — OpenTelemetry bootstrap for the story-generation backend.

Uses Agent Framework's built-in ``configure_otel_providers()`` to set up
the TracerProvider, exporters, and Agent Framework instrumentation from
environment variables.  Also auto-instruments FastAPI so every incoming
HTTP request gets its own trace span automatically.

See: https://learn.microsoft.com/en-us/agent-framework/agents/observability
"""

import logging
import os
from typing import Any

from agent_framework.observability import (
    configure_otel_providers,
    enable_instrumentation,
)
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


def _try_configure_azure_monitor() -> bool:
    """Wire the Azure Monitor exporter if APPLICATIONINSIGHTS_CONNECTION_STRING is set.

    Returns ``True`` iff Azure Monitor was successfully configured (in which
    case the caller should skip the OTLP fallback). Returns ``False`` if the
    connection string is missing, blank, or if the optional
    ``azure-monitor-opentelemetry`` dep isn't installed — both cases degrade
    gracefully so the app never fails to boot just because telemetry isn't
    fully wired.
    """
    conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not conn_str:
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but the "
            "'azure-monitor-opentelemetry' package is not installed (%s); "
            "falling back to configure_otel_providers().",
            exc,
        )
        return False

    try:
        # Disable Azure Monitor's auto FastAPI instrumentation so our explicit
        # FastAPIInstrumentor.instrument_app(...) call below can attach the
        # SSE-body response hook.
        configure_azure_monitor(
            connection_string=conn_str,
            instrumentation_options={"fastapi": {"enabled": False}},
        )
        # Agent Framework's own SDK only emits workflow/executor/chat spans
        # once its instrumentation hook is enabled.
        enable_instrumentation()
    except Exception:  # noqa: BLE001 — telemetry must never crash the app.
        logger.exception(
            "Failed to configure Azure Monitor exporter; "
            "falling back to configure_otel_providers().",
        )
        return False

    logger.info("Azure Monitor OTEL exporter configured for App Insights")
    return True


def _try_instrument_azure_ai_projects() -> None:
    """Enable the Azure AI Projects GenAI instrumentor (Foundry tracing).

    The instrumentor adds rich GenAI semantic-convention spans
    (``create_thread``, ``create_run``, ``process_thread_run``, etc.) and
    — critically — injects W3C ``traceparent`` / ``tracestate`` headers on
    outbound HTTP requests to the Foundry agent endpoints. Without that
    header, server-side Foundry spans land in App Insights with a fresh
    ``trace_id`` and appear as orphaned, "dangling" traces alongside the
    Agent Framework workflow trace.

    Two things are required to activate it:

    * ``AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true`` must be set on the
      process environment. We ``setdefault`` it so it's on by default in
      this app, but an operator can opt out by explicitly setting the env
      var to anything else.
    * ``AIProjectInstrumentor().instrument(...)`` must be called once at
      startup (no-op on subsequent calls).

    The whole thing is wrapped in try/except: telemetry must never block
    application startup. In ``local`` agent-hosting mode the instrumentor
    is harmless — it patches the AIProjectClient class globally, but the
    code path is never exercised.
    """
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")

    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor
    except ImportError as exc:
        logger.warning(
            "AIProjectInstrumentor unavailable (%s); Foundry-hosted agent "
            "spans will not be unified with the Agent Framework trace.",
            exc,
        )
        return

    try:
        AIProjectInstrumentor().instrument(
            # Don't capture prompt / response content into spans by default —
            # keeps spans small and honours ENABLE_SENSITIVE_DATA=false.
            enable_content_recording=False,
            # Inject traceparent on outbound Foundry HTTP so server-side
            # spans join the same trace as our workflow.run span.
            enable_trace_context_propagation=True,
        )
    except Exception:  # noqa: BLE001 — telemetry must never crash the app.
        logger.exception("Failed to enable AIProjectInstrumentor; continuing without it.")
        return

    logger.info(
        "AIProjectInstrumentor enabled (Foundry GenAI spans + trace context propagation)",
    )


def configure_telemetry(app: FastAPI) -> None:
    """Set up OTEL providers and instrument FastAPI.

    This must be called **before** any agent-framework imports that create
    workflows or executors, so the framework can pick up the active
    TracerProvider and emit its own spans.

    Routing precedence:

    1. If ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set (and the optional
       ``azure-monitor-opentelemetry`` package is installed), spans/logs/metrics
       are exported to Azure Application Insights, and the Azure AI Projects
       GenAI instrumentor is enabled so Foundry-hosted agent calls share the
       same trace as the surrounding Agent Framework workflow.
    2. Otherwise, ``configure_otel_providers()`` from Agent Framework runs
       (honours ``OTEL_EXPORTER_OTLP_ENDPOINT``, ``VS_CODE_EXTENSION_PORT``,
       and ``ENABLE_CONSOLE_EXPORTERS`` — covers local dev / AI Toolkit / OTLP
       collector workflows).

    Does nothing if ``settings.otel_enabled`` is False.
    """
    if not settings.otel_enabled:
        logger.info("OpenTelemetry is disabled (OTEL_ENABLED=false)")
        return

    if _try_configure_azure_monitor():
        # Only meaningful when we have a real exporter wired up — the
        # instrumentor needs OTEL spans to actually have somewhere to go.
        _try_instrument_azure_ai_projects()
    else:
        # Fallback path: OTLP / AI Toolkit / local dev. Reads
        # OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, ENABLE_INSTRUMENTATION,
        # and ENABLE_SENSITIVE_DATA from env vars automatically.
        configure_otel_providers()

    # Auto-instrument FastAPI (creates a parent span for every HTTP request).
    # client_response_hook fires for every outgoing ASGI message, letting us
    # capture the SSE event body on each "http send" span.
    FastAPIInstrumentor.instrument_app(app, client_response_hook=_response_hook)

    logger.info("OpenTelemetry configured (FastAPI instrumented)")
