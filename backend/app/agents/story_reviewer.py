"""
StoryReviewerExecutor — Fourth node in the workflow.

Receives the fully illustrated StoryDraft and performs a comprehensive
quality review, producing a ReviewResult that the DecisionExecutor uses
to either approve or request revisions.
"""

import json
import logging
from urllib.parse import urlparse

from agent_framework import (
    ChatAgent,
    ChatMessage,
    DataContent,
    Executor,
    TextContent,
    WorkflowContext,
    handler,
)
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..models import StoryDraft, ReviewResult
from ..prompts import STORY_REVIEWER_INSTRUCTIONS
from ..storage import get_backend
from ..utils import parse_llm_json, record_llm_usage
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

        # Retrieve the canonical character list from shared state so the reviewer can
        # cross-check every image_prompt against the officially defined characters.
        character_descriptions: dict[str, str] = {}
        outline_json = await ctx.get_shared_state("outline")
        if outline_json:
            try:
                outline_data = json.loads(outline_json)
                character_descriptions = outline_data.get("character_descriptions", {})
            except Exception:
                pass  # graceful degradation — review still proceeds without it

        # On revision rounds, surface the previous round's instructions so the reviewer
        # can verify the requested fixes actually landed. ``get_shared_state`` raises
        # KeyError when the key is absent, so guard both reads — they're absent on the
        # very first review pass.
        try:
            revision_count = (await ctx.get_shared_state("revision_count")) or 0
        except KeyError:
            revision_count = 0
        try:
            prior_revision_instructions = (
                await ctx.get_shared_state("last_revision_instructions")
            ) or ""
        except KeyError:
            prior_revision_instructions = ""

        try:
            session_id = await ctx.get_shared_state("session_id")
        except KeyError:
            session_id = None

        prompt_text = self._build_review_prompt(
            draft,
            character_descriptions,
            revision_count=revision_count,
            prior_revision_instructions=prior_revision_instructions,
        )

        # Build a multimodal user message: text intro + per-page (text header + image),
        # then cover and "the end" images at the end.
        review_message = self._build_review_message(draft, prompt_text, session_id)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="prompt_sent",
            detail_data={
                "prompt": prompt_text,
                "title": draft.title,
                "page_count": len(draft.pages),
                "revision_round": revision_count,
                "image_count": sum(
                    1 for c in review_message.contents if isinstance(c, DataContent)
                ),
            },
        ))

        result = await self._agent.run(review_message)
        record_llm_usage(result)
        review = ReviewResult.model_validate(parse_llm_json(result.text))

        # Stash this round's instructions so the next review can verify them.
        await ctx.set_shared_state(
            "last_revision_instructions", review.revision_instructions
        )

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="response_received",
            detail_data={
                "approved": review.approved,
                "issue_count": len(review.issues),
                "issues": [
                    {
                        "page": i.page_number,
                        "category": i.category,
                        "severity": i.severity,
                        "description": i.description,
                    }
                    for i in review.issues
                ],
                "revision_instructions": review.revision_instructions,
                "category_passes": {
                    "character_consistency": review.character_consistency_pass,
                    "narrative_coherence": review.narrative_coherence_pass,
                    "age_appropriateness": review.age_appropriateness_pass,
                    "moral_integration": review.moral_integration_pass,
                    "art_text_alignment": review.art_text_alignment_pass,
                },
            },
        ))

        status = "APPROVED" if review.approved else f"REJECTED ({len(review.issues)} issue(s))"
        logger.info("[StoryReviewer] Review result: %s", status)

        if not review.approved:
            for issue in review.issues:
                logger.info(
                    "[StoryReviewer]   Issue (page %s, %s, severity=%s): %s",
                    issue.page_number or "whole story",
                    issue.category,
                    issue.severity,
                    issue.description,
                )

        await ctx.send_message(review)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_review_prompt(
        self,
        draft: StoryDraft,
        character_descriptions: dict[str, str] | None = None,
        *,
        revision_count: int = 0,
        prior_revision_instructions: str = "",
    ) -> str:
        pages_summary = "\n\n".join(
            (
                f"--- PAGE {p.page_number} ---\n"
                f"Text: {p.text}\n"
                f"Characters present: {', '.join(p.characters_present)}\n"
                f"Emotional tone: {p.emotional_tone}\n"
                f"Image prompt: {p.image_prompt}\n"
                f"Image generated: {'Yes (attached below page metadata)' if p.image_url else 'No (generation failed — flag this as a high-severity art_text_alignment issue)'}"
            )
            for p in draft.pages
        )

        char_desc_section = ""
        if character_descriptions:
            char_lines = "\n".join(
                f"  - {name}: {desc}"
                for name, desc in character_descriptions.items()
            )
            char_desc_section = (
                "\nCANONICAL CHARACTER DESCRIPTIONS "
                "(the ONLY characters that should ever appear in any image prompt):\n"
                + char_lines
            )

        revision_section = ""
        if revision_count and prior_revision_instructions:
            revision_section = (
                f"\nTHIS IS REVISION ROUND {revision_count}. The previous review issued"
                " these revision instructions:\n"
                f"{prior_revision_instructions}\n"
                "You MUST verify that EACH numbered item above was addressed in this"
                " revision. If any was not, reject the story again and call out which"
                " items were missed in your new revision_instructions."
            )

        return "\n".join([
            f"Please review this complete children's story titled '{draft.title}'.",
            "",
            "The actual rendered illustrations are attached as inline images, interleaved",
            "with the per-page metadata. Compare each image to its page text AND compare",
            "each named character's appearance across all pages they appear in.",
            "",
            "PAGES:",
            pages_summary,
            "",
            f"MORAL SUMMARY (final page closing): {draft.moral_summary}",
            char_desc_section,
            revision_section,
            "",
            (
                "Return a single ReviewResult JSON object as defined in your system"
                " instructions, including the per-category pass booleans and a severity"
                " on every issue."
            ),
        ])

    def _build_review_message(
        self,
        draft: StoryDraft,
        prompt_text: str,
        session_id: str | None,
    ) -> ChatMessage:
        """
        Build a multimodal user message: prompt text first, then for each page a small
        text header followed by the rendered image (when available), then cover + end.
        """
        contents: list = [TextContent(text=prompt_text)]

        backend = get_backend()

        def _image_for(image_url: str | None, label: str) -> None:
            if not image_url or not session_id:
                return
            filename = self._filename_from_url(image_url)
            if not filename:
                return
            try:
                png_bytes = backend.get_draft_image_bytes(session_id, filename)
            except Exception:  # noqa: BLE001 — never let image fetch break review
                logger.warning(
                    "[StoryReviewer] Could not fetch %s image bytes (%s)", label, filename
                )
                return
            if not png_bytes:
                return
            contents.append(TextContent(text=f"\n[Attached image: {label}]"))
            contents.append(
                DataContent(data=png_bytes, media_type="image/png")
            )

        # Cover first so the reviewer establishes the visual baseline
        _image_for(draft.cover_image_url, "Cover")

        for page in draft.pages:
            _image_for(page.image_url, f"Page {page.page_number}")

        _image_for(draft.the_end_image_url, "The End")

        return ChatMessage(role="user", contents=contents)

    @staticmethod
    def _filename_from_url(image_url: str) -> str | None:
        """Extract the trailing filename from a draft image URL.

        Accepts either an absolute URL or a path like
        ``/api/drafts/<sid>/images/<filename>.png``.
        """
        path = urlparse(image_url).path or image_url
        if "/" not in path:
            return None
        return path.rsplit("/", 1)[-1] or None
