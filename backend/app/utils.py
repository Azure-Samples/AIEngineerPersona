"""Utility helpers shared across agent executors."""

import logging
from collections.abc import Mapping
from typing import Any

from opentelemetry import trace

logger = logging.getLogger(__name__)


def _read_usage_field(usage: Any, key: str) -> int | None:
    """Read a token-count field from a UsageDetails value.

    In agent-framework 1.3.0, ``AgentResponse.usage_details`` is a TypedDict
    (``UsageDetails``), so fields are accessed by key. Earlier prereleases used
    an attribute-style object. This helper supports both shapes so an upstream
    framework change can't quietly break OTEL instrumentation.
    """
    if isinstance(usage, Mapping):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    if isinstance(value, int):
        return value
    return None


def record_llm_usage(result: Any, **extra_attributes: str | int | float | bool) -> None:
    """Record LLM token usage and any extra attributes on the current OTEL span.

    Call this after any ``self._agent.run(prompt)`` call. Gracefully does
    nothing if tracing is disabled or if the result carries no usage data.

    Args:
        result: The ``AgentResponse`` returned by ``agent.run()``.
        **extra_attributes: Additional span attributes to set alongside the
            token counts (e.g. ``title="My Story"``, ``approved=True``).
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return

    usage = getattr(result, "usage_details", None)
    if usage is not None:
        prompt_tokens = _read_usage_field(usage, "input_token_count")
        if prompt_tokens is not None:
            span.set_attribute("llm.token_count.prompt", prompt_tokens)
        completion_tokens = _read_usage_field(usage, "output_token_count")
        if completion_tokens is not None:
            span.set_attribute("llm.token_count.completion", completion_tokens)
        total_tokens = _read_usage_field(usage, "total_token_count")
        if total_tokens is not None:
            span.set_attribute("llm.token_count.total", total_tokens)

    for key, value in extra_attributes.items():
        span.set_attribute(key, value)
