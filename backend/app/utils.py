"""Utility helpers shared across agent executors."""

import json
import re
import logging

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
