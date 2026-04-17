"""
DecisionExecutor — Fifth and final node in the workflow (routing logic).

Receives the ReviewResult and decides:
  - If approved OR max revision cycles reached → assemble StoryResponse and yield_output
  - If rejected AND revision budget remains → send RevisionSignal back to OrchestratorExecutor

This node creates the conditional loop in the workflow graph:
  DecisionExecutor → OrchestratorExecutor  (back-edge, revision path)
  DecisionExecutor → yield_output          (terminal path, approved / exhausted)
"""

import logging

from agent_framework import Executor, WorkflowContext, handler

from ..config import settings
from ..events import ProgressDetailEvent
from ..models import ReviewResult, StoryDraft, StoryResponse
from ..signals import RevisionSignal

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 2


class DecisionExecutor(Executor):
    """
    Routes the workflow: approve & emit final story, or loop back for revision.
    """

    def __init__(self) -> None:
        super().__init__(id="decision")

    @handler
    async def handle_illustrated_draft(
        self,
        draft: StoryDraft,
        ctx: WorkflowContext[ReviewResult, StoryResponse],
    ) -> None:
        """Auto-approve path used when SKIP_STORY_REVIEWER=true."""
        logger.info(
            "[Decision] SKIP_STORY_REVIEWER is enabled — auto-approving '%s'.",
            draft.title,
        )
        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="auto_approved",
            detail_data={"title": draft.title},
        ))
        auto_review = ReviewResult(approved=True, issues=[], revision_instructions="")
        await self.handle_review(auto_review, ctx)

    @handler
    async def handle_review(
        self,
        review: ReviewResult,
        ctx: WorkflowContext[RevisionSignal, StoryResponse],
    ) -> None:
        revision_count = await ctx.get_shared_state("revision_count") or 0
        budget_exhausted = revision_count >= MAX_REVISION_ROUNDS

        if review.approved or budget_exhausted:
            if not review.approved:
                logger.warning(
                    "[Decision] Revision budget exhausted after %d round(s). "
                    "Proceeding with best available story despite %d issue(s).",
                    revision_count,
                    len(review.issues),
                )
            else:
                logger.info(
                    "[Decision] Story approved after %d revision round(s).",
                    revision_count,
                )

            story_response = await self._assemble_story(review, revision_count, ctx)
            await ctx.yield_output(story_response)

        else:
            logger.info(
                "[Decision] Story rejected — sending revision signal "
                "(round %d/%d). Issues: %d",
                revision_count + 1,
                MAX_REVISION_ROUNDS,
                len(review.issues),
            )
            signal = RevisionSignal(
                revision_instructions=review.revision_instructions,
                revision_round=revision_count + 1,
            )
            await ctx.send_message(signal)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    async def _assemble_story(
        self,
        review: ReviewResult,
        revision_rounds: int,
        ctx: WorkflowContext,
    ) -> StoryResponse:
        """Pull the illustrated draft from workflow state and build the final response."""
        draft_json = await ctx.get_shared_state("illustrated_draft")
        if not draft_json:
            raise RuntimeError(
                "DecisionExecutor: 'illustrated_draft' not found in workflow state. "
                "This should not happen — ArtDirectorExecutor must run first."
            )

        draft = StoryDraft.model_validate_json(draft_json)

        issue_summary = ""
        if review.issues:
            lines = [f"- [{i.category}] {i.description}" for i in review.issues]
            issue_summary = "Minor notes from reviewer:\n" + "\n".join(lines)

        return StoryResponse(
            title=draft.title,
            pages=draft.pages,
            moral_summary=draft.moral_summary,
            cover_image_url=draft.cover_image_url,
            the_end_image_url=draft.the_end_image_url,
            review_notes=issue_summary if issue_summary else "Story approved with no issues.",
            revision_rounds=revision_rounds,
        )
