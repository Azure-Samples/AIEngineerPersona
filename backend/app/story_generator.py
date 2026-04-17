"""
story_generator.py — SSE event generator for the story workflow.

Encapsulates the logic that runs the multi-agent story workflow and translates
framework events into Server-Sent Event payloads consumed by the frontend.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from sse_starlette.sse import EventSourceResponse

from .events import ProgressDetailEvent
from .models import StoryRequest, StoryResponse
from .workflow import story_workflow

try:
    from agent_framework import (
        ExecutorInvokedEvent,
        ExecutorCompletedEvent,
        WorkflowOutputEvent,
    )
    try:
        from agent_framework import WorkflowFailedEvent
    except ImportError:
        WorkflowFailedEvent = None  # type: ignore[misc,assignment]
except ImportError as _ie:
    raise RuntimeError(f"agent_framework event classes unavailable: {_ie}") from _ie

logger = logging.getLogger(__name__)


class StoryGenerator:
    """Runs the story workflow and streams SSE progress events to the client.

    Usage::

        generator = StoryGenerator()

        # Inside a FastAPI route:
        return generator.event_source_response(request)
    """

    EXECUTOR_LABELS: dict[str, str] = {
        "orchestrator":    "Orchestrator",
        "story_architect": "Story Architect",
        "art_director":    "Art Director",
        "story_reviewer":  "Story Reviewer",
        "decision":        "Decision",
    }

    EXECUTOR_MESSAGES: dict[str, str] = {
        "orchestrator":    "Creating the story outline...",
        "story_architect": "Writing the story pages...",
        "art_director":    "Generating illustrations for each page...",
        "story_reviewer":  "Reviewing story for quality & consistency...",
        "decision":        "Making final decisions...",
    }

    # ── Public API ────────────────────────────────────────────────────────

    def event_source_response(self, request: StoryRequest) -> EventSourceResponse:
        """Return an ``EventSourceResponse`` that streams SSE events for the
        given story request.
        """
        logger.info(
            "[API] New story generation request — main character: '%s'",
            request.main_character,
        )
        return EventSourceResponse(
            self._generate_events(request),
            media_type="text/event-stream",
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _sse_event(event_type: str, data: dict) -> dict:
        """Format a single Server-Sent Event payload."""
        return {"event": event_type, "data": json.dumps(data)}

    async def _generate_events(
        self,
        request: StoryRequest,
    ) -> AsyncGenerator[dict, None]:
        """Run the story workflow and translate WorkflowEvents into SSE messages.

        SSE event types emitted to the frontend:
          - ``progress`` — executor started / completed
          - ``detail``   — granular sub-step detail (prompt, response, page content, image progress)
          - ``revision`` — a revision loop has been triggered
          - ``complete`` — final StoryResponse (story is done)
          - ``error``    — workflow failed
        """
        try:
            revision_count = 0
            active_executor: str | None = None

            async for event in story_workflow.run_stream(request):

                if isinstance(event, ExecutorInvokedEvent):
                    executor_id: str = event.executor_id or ""
                    active_executor = executor_id
                    label = self.EXECUTOR_LABELS.get(executor_id, executor_id)
                    message = self.EXECUTOR_MESSAGES.get(
                        executor_id, f"{label} is working..."
                    )

                    # Detect revision loops: orchestrator re-invoked after the first pass.
                    # We can't easily read revision_count from the event, so we track locally.
                    is_revision = (
                        executor_id == "orchestrator" and revision_count > 0
                    )

                    if is_revision:
                        yield self._sse_event(
                            "revision",
                            {
                                "executor_id": executor_id,
                                "revision_round": revision_count,
                                "message": (
                                    f"Story Reviewer requested changes "
                                    f"— starting revision {revision_count}..."
                                ),
                            },
                        )
                    else:
                        yield self._sse_event(
                            "progress",
                            {
                                "executor_id": executor_id,
                                "status": "started",
                                "label": label,
                                "message": message,
                            },
                        )

                elif isinstance(event, ExecutorCompletedEvent):
                    executor_id = event.executor_id or (active_executor or "")
                    label = self.EXECUTOR_LABELS.get(executor_id, executor_id)
                    if executor_id == "decision":
                        # Increment our local revision counter each time decision completes
                        # without yielding output (proxy: orchestrator will fire again).
                        revision_count += 1
                    yield self._sse_event(
                        "progress",
                        {
                            "executor_id": executor_id,
                            "status": "completed",
                            "label": label,
                            "message": f"{label} finished.",
                        },
                    )

                elif isinstance(event, ProgressDetailEvent):
                    yield self._sse_event(
                        "detail",
                        {
                            "executor_id": event.executor_id,
                            "detail_type": event.detail_type,
                            "data": event.detail_data,
                        },
                    )

                elif isinstance(event, WorkflowOutputEvent):
                    output_data = event.data
                    if output_data is not None:
                        if isinstance(output_data, StoryResponse):
                            story_dict = output_data.model_dump()
                        elif hasattr(output_data, "model_dump"):
                            story_dict = output_data.model_dump()
                        elif isinstance(output_data, dict):
                            story_dict = output_data
                        else:
                            story_dict = json.loads(str(output_data))

                        # Reset revision counter for clean final event
                        revision_count = 0
                        yield self._sse_event("complete", {"story": story_dict})

                elif (
                    WorkflowFailedEvent is not None
                    and isinstance(event, WorkflowFailedEvent)
                ):
                    details = getattr(event, "details", None)
                    if details is not None:
                        error_msg = (
                            getattr(details, "message", None) or str(details)
                        )
                        executor = getattr(details, "executor_id", None)
                        tb = getattr(details, "traceback", None)
                        logger.error(
                            "[Workflow] Workflow failed in executor=%s: %s\n%s",
                            executor,
                            error_msg,
                            tb or "",
                        )
                    else:
                        error_msg = "The story workflow encountered an error."
                        logger.error("[Workflow] Workflow failed (no details)")
                    yield self._sse_event(
                        "error",
                        {
                            "message": (
                                error_msg
                                or "The story workflow encountered an error."
                            )
                        },
                    )
                    return

        except Exception as exc:
            logger.exception(
                "[Workflow] Unhandled error in story event generator"
            )
            yield self._sse_event(
                "error", {"message": f"Internal error: {exc}"}
            )
