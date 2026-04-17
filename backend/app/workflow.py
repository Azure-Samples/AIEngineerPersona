"""
workflow.py — Constructs the children's story multi-agent workflow.

Base graph topology (always present):

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
            │ StoryResponse (approved)
            ▼
     Bonus agent fan-out (0, 1, or 2 agents depending on request flags):

   ─── No bonus agents ─────────────────────────────────────────────────────────
   Decision → FinalAssembly

   ─── Look & Find only ────────────────────────────────────────────────────────
   Decision → LookAndFind → FinalAssembly

   ─── Character Glossary only ─────────────────────────────────────────────────
   Decision → CharacterGlossary → FinalAssembly

   ─── Both bonus agents (fan-out / fan-in) ───────────────────────────────────
   Decision ──fan-out──► LookAndFind ──┐
                     └► CharacterGlossary ──┤
                                       fan-in ──► FinalAssembly → yield_output

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
from .agents.approval_gateway import ApprovalGatewayExecutor
from .agents.look_and_find import LookAndFindActivityExecutor
from .agents.character_glossary import CharacterGlossaryExecutor
from .agents.final_assembly import FinalAssemblyExecutor


def build_story_workflow(request: StoryRequest) -> Workflow:
    """
    Build and return a Workflow for the given request.

    The graph topology varies per-request based on flags in StoryRequest
    (enable_story_reviewer, include_look_and_find, include_character_glossary).

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
    approval_gateway   = ApprovalGatewayExecutor()
    final_assembly     = FinalAssemblyExecutor()

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

    # ── Approval gateway ──────────────────────────────────────────────────
    # DecisionExecutor outputs two types: StoryResponse (approved) and
    # RevisionSignal (rejected).  The framework type validator requires ALL
    # output types of a source to be compatible with every target's inputs.
    # ApprovalGatewayExecutor accepts only StoryResponse, making the edge
    # decision → approval_gateway type-safe, and then fans out to bonus agents.
    builder = builder.add_edge(decision, approval_gateway)

    # ── Bonus agent fan-out / fan-in ───────────────────────────────────────
    if request.include_look_and_find and request.include_character_glossary:
        # Both agents enabled — true parallel fan-out / fan-in
        look_and_find      = LookAndFindActivityExecutor()
        character_glossary = CharacterGlossaryExecutor()
        builder = (
            builder
            .add_fan_out_edges(approval_gateway, [look_and_find, character_glossary])
            .add_fan_in_edges([look_and_find, character_glossary], final_assembly)
        )

    elif request.include_look_and_find:
        look_and_find = LookAndFindActivityExecutor()
        builder = (
            builder
            .add_edge(approval_gateway, look_and_find)
            .add_edge(look_and_find, final_assembly)
        )

    elif request.include_character_glossary:
        character_glossary = CharacterGlossaryExecutor()
        builder = (
            builder
            .add_edge(approval_gateway, character_glossary)
            .add_edge(character_glossary, final_assembly)
        )

    else:
        # No bonus agents — gateway forwards StoryResponse directly to FinalAssembly
        builder = builder.add_edge(approval_gateway, final_assembly)

    return builder.build()

