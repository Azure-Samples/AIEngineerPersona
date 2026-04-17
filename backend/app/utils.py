"""Utility helpers shared across agent executors."""

import json
import re
import logging
from typing import Any

from opentelemetry import trace

logger = logging.getLogger(__name__)


def extract_json_from_response(text: str) -> str:
    """
    Pull JSON out of an LLM response that may be wrapped in markdown code fences.
    Falls back to the raw text so Pydantic can attempt to parse it.
    """
    # Try ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try to find a bare JSON object or array
    json_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()

    return text.strip()


def build_system_and_user_messages(system: str, user: str) -> list[dict]:
    """Build a minimal chat message list for use with Agent.run()."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def record_llm_usage(result: Any, **extra_attributes: str | int | float | bool) -> None:
    """Record LLM token usage and any extra attributes on the current OTEL span.

    Call this after any ``self._agent.run(prompt)`` call. Gracefully does nothing
    if tracing is disabled or if the result carries no usage data.

    Args:
        result: The ``AgentRunResponse`` returned by ``agent.run()``.
        **extra_attributes: Additional span attributes to set alongside the
            token counts (e.g. ``title="My Story"``, ``approved=True``).
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return

    usage = getattr(result, "usage_details", None)
    if usage:
        if usage.input_token_count is not None:
            span.set_attribute("llm.token_count.prompt", usage.input_token_count)
        if usage.output_token_count is not None:
            span.set_attribute("llm.token_count.completion", usage.output_token_count)
        if usage.total_token_count is not None:
            span.set_attribute("llm.token_count.total", usage.total_token_count)

    for key, value in extra_attributes.items():
        span.set_attribute(key, value)
