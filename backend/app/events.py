"""
events.py — Custom Agent Framework workflow events for granular SSE progress reporting.

Executors call:
    await ctx.add_event(ProgressDetailEvent(
        executor_id="art_director",
        detail_type="image_started",
        detail_data={"page_number": 1, "total_pages": 8, "prompt": "..."},
    ))

main.py translates these into SSE events of type "detail" for the frontend.
"""

from typing import Any

from agent_framework import WorkflowEvent


class ProgressDetailEvent(WorkflowEvent):
    """
    Emitted by individual executor handlers to provide sub-step detail
    that goes beyond the built-in ExecutorInvokedEvent / ExecutorCompletedEvent.

    detail_type values:
        "prompt_sent"         — the exact prompt sent to the LLM
        "response_received"   — the LLM response / parsed result summary
        "page_content"        — a single page of story text has been parsed
        "image_started"       — an image generation request has been dispatched
        "image_completed"     — an image generation request has succeeded
        "image_failed"        — an image generation request has failed
    """

    def __init__(
        self,
        executor_id: str,
        detail_type: str,
        detail_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(data=detail_data)
        self.executor_id = executor_id
        self.detail_type = detail_type
        self.detail_data: dict[str, Any] = detail_data or {}
