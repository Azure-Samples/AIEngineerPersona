"""
workflow.py — Constructs the children's story multi-agent workflow.

Graph topology:
                     ┌─────────────────────────────────────────────┐
                     │  (RevisionSignal — revision loop back-edge)  │
                     ▼                                               │
            ┌─────────────────┐                                      │
  Start ──► │   Orchestrator  │                                      │
            └────────┬────────┘                                      │
                     │ (StoryOutline)                                │
                     ▼                                               │
            ┌─────────────────┐                                      │
            │  StoryArchitect │                                      │
            └────────┬────────┘                                      │
                     │ (StoryDraft — text only)                      │
                     ▼                                               │
            ┌─────────────────┐                                      │
            │   ArtDirector   │                                      │
            └────────┬────────┘                                      │
                     │ (StoryDraft — with image_url populated)       │
                     ▼                                               │
            ┌─────────────────┐                                      │
            │  StoryReviewer  │                                      │
            └────────┬────────┘                                      │
                     │ (ReviewResult)                                │
                     ▼                                               │
            ┌─────────────────┐                                      │
            │    Decision     │ ───────────────────────────────────►─┘
            └────────┬────────┘
                     │ (yield_output → StoryResponse — approved or budget exhausted)
                     ▼
                  [Done]
"""

from agent_framework import WorkflowBuilder, Workflow

from .config import settings
from .agents.orchestrator import OrchestratorExecutor
from .agents.story_architect import StoryArchitectExecutor
from .agents.art_director import ArtDirectorExecutor
from .agents.story_reviewer import StoryReviewerExecutor
from .agents.decision import DecisionExecutor


def build_story_workflow() -> Workflow:
    """
    Instantiate all executors and wire them into the sequential workflow
    with a conditional back-edge for the revision loop.

    Returns an immutable Workflow ready to call with .run(story_request).
    """
    orchestrator = OrchestratorExecutor()
    story_architect = StoryArchitectExecutor()
    art_director = ArtDirectorExecutor()
    story_reviewer = StoryReviewerExecutor()
    decision = DecisionExecutor()

    builder = (
        WorkflowBuilder()
        .set_start_executor(orchestrator)
        .set_max_iterations(30)
        # Forward sequential edges
        .add_edge(orchestrator, story_architect)
        .add_edge(story_architect, art_director)
    )

    if settings.skip_story_reviewer:
        # Bypass the LLM reviewer — ArtDirector output goes straight to Decision,
        # which will auto-approve via its StoryDraft handler.
        builder = builder.add_edge(art_director, decision)
    else:
        builder = (
            builder
            .add_edge(art_director, story_reviewer)
            .add_edge(story_reviewer, decision)
        )

    workflow = (
        builder
        # Back-edge: DecisionExecutor loops to OrchestratorExecutor when revision is needed.
        # On approval (or budget exhaustion) DecisionExecutor calls ctx.yield_output()
        # instead of ctx.send_message(), so this edge is not traversed.
        .add_edge(decision, orchestrator)
        .build()
    )

    return workflow


# Module-level singleton — created once at import / app startup
story_workflow: Workflow = build_story_workflow()
