"""
StoryReviewerExecutor — Fourth node in the workflow.

Receives the fully illustrated StoryDraft and performs a comprehensive
quality review, producing a ReviewResult that the DecisionExecutor uses
to either approve or request revisions.
"""

import logging

from agent_framework import ChatAgent, Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..models import StoryDraft, ReviewResult
from ..prompts import STORY_REVIEWER_INSTRUCTIONS
from ..utils import extract_json_from_response
from ..events import ProgressDetailEvent

logger = logging.getLogger(__name__)


class StoryReviewerExecutor(Executor):
    """
    Reviews the complete illustrated story for character consistency,
    narrative coherence, age-appropriateness, moral integration, and
    art-text alignment.
    """

    def __init__(self) -> None:
        super().__init__(id="story_reviewer")
        self._agent = ChatAgent(
            name="StoryReviewerAgent",
            instructions=STORY_REVIEWER_INSTRUCTIONS,
            chat_client=AzureOpenAIChatClient(
                endpoint=settings.foundry_project_endpoint,
                deployment_name=settings.foundry_model_deployment_name,
                credential=DefaultAzureCredential(),
            ),
        )

    @handler
    async def handle_illustrated_draft(
        self,
        draft: StoryDraft,
        ctx: WorkflowContext[ReviewResult],
    ) -> None:
        logger.info(
            "[StoryReviewer] Reviewing '%s' (%d pages)",
            draft.title,
            len(draft.pages),
        )

        prompt = self._build_review_prompt(draft)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "title": draft.title, "page_count": len(draft.pages)},
        ))

        result = await self._agent.run(prompt)
        raw_json = extract_json_from_response(result.text)
        review = ReviewResult.model_validate_json(raw_json)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="response_received",
            detail_data={
                "approved": review.approved,
                "issue_count": len(review.issues),
                "issues": [
                    {"page": i.page_number, "category": i.category, "description": i.description}
                    for i in review.issues
                ],
                "revision_instructions": review.revision_instructions,
            },
        ))

        status = "APPROVED" if review.approved else f"REJECTED ({len(review.issues)} issue(s))"
        logger.info("[StoryReviewer] Review result: %s", status)

        if not review.approved:
            for issue in review.issues:
                logger.info(
                    "[StoryReviewer]   Issue (page %s, %s): %s",
                    issue.page_number or "whole story",
                    issue.category,
                    issue.description,
                )

        await ctx.send_message(review)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_review_prompt(self, draft: StoryDraft) -> str:
        pages_summary = "\n\n".join(
            (
                f"--- PAGE {p.page_number} ---\n"
                f"Text: {p.text}\n"
                f"Characters present: {', '.join(p.characters_present)}\n"
                f"Emotional tone: {p.emotional_tone}\n"
                f"Image prompt: {p.image_prompt}\n"
                f"Image generated: {'Yes' if p.image_url else 'No (generation failed)'}"
            )
            for p in draft.pages
        )

        return "\n".join([
            f"Please review this complete children's story titled '{draft.title}'.",
            "",
            "PAGES:",
            pages_summary,
            "",
            f"MORAL SUMMARY (final page closing): {draft.moral_summary}",
            "",
            (
                "Return a ReviewResult JSON object with: approved (bool), "
                "issues (list of {page_number, category, description}), "
                "and revision_instructions (string — empty string if approved)."
            ),
        ])
