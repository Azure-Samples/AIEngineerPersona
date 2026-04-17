"""
workflow.py — Constructs the children's story multi-agent workflow.

Graph topology:

            ┌─────────────────────────────────────────────┐
            │  (RevisionSignal — revision loop back-edge)  │
            ▼                                              │
   ┌─────────────────┐                                     │
   │   Orchestrator  │                                     │
   └────────┬────────┘                                     │
            │ StoryOutline                                 │
            ▼                                              │
   ┌─────────────────┐                                     │
   │  StoryArchitect │                                     │
   └────────┬────────┘                                     │
            │ StoryDraft (text only)                       │
            ▼                                              │
   ┌─────────────────┐                                     │
   │   ArtDirector   │                                     │
   └────────┬────────┘                                     │
            │ StoryDraft (with image_url)                  │
            ▼                                              │
   [StoryReviewer?]  ← conditional edge; runs when enable_story_reviewer=true
            │ ReviewResult                                 │
            ▼                                              │
   ┌─────────────────┐                                     │
   │    Decision     │────────────────────────────────────►┘
   └────────┬────────┘
            │ yield_output(StoryResponse)

NOTE: build_story_workflow() is called per-request so the graph topology can vary
based on the flags in StoryRequest. There is no module-level singleton.
"""

from agent_framework import WorkflowBuilder, Workflow

from .models import StoryRequest
from .agents.orchestrator import OrchestratorExecutor
from .agents.story_architect import StoryArchitectExecutor
from .agents.art_director import ArtDirectorExecutor
from .agents.story_reviewer import StoryReviewerExecutor
from .agents.decision import DecisionExecutor


def build_story_workflow(request: StoryRequest) -> Workflow:
    """
    Build and return a Workflow for the given request.

    The graph topology varies per-request based on flags in StoryRequest
    (enable_story_reviewer).

    Args:
        request: The story generation request containing all user options.

    Returns:
        An immutable Workflow ready to call with workflow.run_stream(story_request).
    """
    orchestrator       = OrchestratorExecutor()
    story_architect    = StoryArchitectExecutor()
    art_director       = ArtDirectorExecutor()
    story_reviewer     = StoryReviewerExecutor()
    decision           = DecisionExecutor()

    builder = (
        WorkflowBuilder()
        .set_start_executor(orchestrator)
        .set_max_iterations(30)
        # ── Core sequential chain ──────────────────────────────────────────
        .add_edge(orchestrator, story_architect)
        .add_edge(story_architect, art_director)
    )

    # ── Conditional edge function for the story reviewer ─────────────────
    def should_review(msg: object) -> bool:
        """Route to the story reviewer when it is enabled."""
        return request.enable_story_reviewer

    # ── Story reviewer (conditional edges) ────────────────────────────────
    # Both edges are always present in the graph; at runtime only one fires.
    builder = (
        builder
        .add_edge(art_director, story_reviewer, condition=should_review)
        .add_edge(art_director, decision, condition=lambda msg: not should_review(msg))
        .add_edge(story_reviewer, decision)
    )

    # ── Revision back-edge (always present) ───────────────────────────────
    # When Decision rejects the story, it sends a RevisionSignal back to
    # Orchestrator.  The framework routes by message type so this edge is
    # only traversed for RevisionSignal messages.
    builder = builder.add_edge(decision, orchestrator)

    return builder.build()

