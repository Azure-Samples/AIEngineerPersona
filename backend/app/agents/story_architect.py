"""
StoryArchitectExecutor — Second node in the workflow.

Receives a StoryOutline from the OrchestratorExecutor and writes the full
narrative text + image prompts for every page, producing a StoryDraft.
"""

import logging

from agent_framework import Executor, WorkflowContext, handler

from ..agent_factory import build_chat_agent, run_structured
from ..models import StoryArchitectOutput, StoryDraft, StoryOutline, StoryPage
from ..prompts import STORY_ARCHITECT_INSTRUCTIONS, get_art_style_phrase
from ..utils import record_llm_usage
from ..events import ProgressDetailEvent

logger = logging.getLogger(__name__)


class StoryArchitectExecutor(Executor):
    """
    Writes the complete story text and image prompts for each page based
    on the outline produced by the OrchestratorExecutor.
    """

    def __init__(self) -> None:
        super().__init__(id="story_architect")
        self._agent = build_chat_agent(
            name="StoryArchitectAgent",
            instructions=STORY_ARCHITECT_INSTRUCTIONS,
        )

    @handler
    async def handle_outline(
        self,
        outline: StoryOutline,
        ctx: WorkflowContext[StoryDraft],
    ) -> None:
        logger.info(
            "[StoryArchitect] Writing story for '%s' (%d pages)",
            outline.title,
            outline.target_pages,
        )

        # Persist the outline so the DecisionExecutor can include it in the
        # final StoryResponse metadata if needed.
        ctx.set_state("outline", outline.model_dump_json())

        prompt = self._build_prompt(outline)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_architect",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "title": outline.title, "page_count": outline.target_pages},
        ))

        result, output = await run_structured(
            self._agent,
            prompt,
            response_format=StoryArchitectOutput,
            # See orchestrator.py for context — gpt-5.x reasoning tokens
            # eat the default response budget and truncate the JSON mid-
            # string. The architect's output is the largest in the workflow
            # (full text + scene_description + image_prompt for 8–10 pages
            # ≈ 8–12k JSON chars), so cap it generously.
            max_tokens=24000,
        )
        record_llm_usage(result)

        # The model emits a StoryArchitectOutput (text-only). Convert to the
        # runtime StoryDraft so downstream executors (ArtDirector, Reviewer,
        # FinalAssembly) can fill in image_url / cover_image_url /
        # the_end_image_url as they run.
        draft = StoryDraft(
            title=output.title,
            pages=[StoryPage(**page.model_dump()) for page in output.pages],
            moral_summary=output.moral_summary,
        )

        # Belt-and-suspenders: append a hard negative constraint to every image prompt so
        # DALL-E cannot render characters who are not present on this page, regardless of
        # whether the LLM faithfully followed the system-prompt instructions.
        for page in draft.pages:
            if page.characters_present:
                present_details = "; ".join(
                    f"{name} ({outline.character_descriptions.get(name, name)})"
                    for name in page.characters_present
                )
                page.image_prompt = (
                    page.image_prompt.rstrip(" .")
                    + f". ONLY the following character(s) must appear in this image: {present_details}."
                    " Do NOT include any other people, animals, or living creatures of any kind."
                    " No bystanders, background figures, or unnamed characters."
                )

        # Emit each page as it's parsed so the frontend can show content streaming in
        for page in draft.pages:
            await ctx.add_event(ProgressDetailEvent(
                executor_id="story_architect",
                detail_type="page_content",
                detail_data={
                    "page_number": page.page_number,
                    "total_pages": len(draft.pages),
                    "text": page.text,
                    "emotional_tone": page.emotional_tone,
                    "characters_present": page.characters_present,
                    "image_prompt": page.image_prompt,
                },
            ))

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_architect",
            detail_type="response_received",
            detail_data={
                "title": draft.title,
                "page_count": len(draft.pages),
                "moral_summary": draft.moral_summary,
            },
        ))

        logger.info(
            "[StoryArchitect] Draft complete: '%s' with %d pages",
            draft.title,
            len(draft.pages),
        )
        await ctx.send_message(draft)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_prompt(self, outline: StoryOutline) -> str:
        char_desc_lines = "\n".join(
            f"  - {name}: {desc}"
            for name, desc in outline.character_descriptions.items()
        )
        page_outline_lines = "\n".join(
            (
                f"  Page {p.page_number}: {p.plot_point}\n"
                f"    Scene: {p.scene_summary}\n"
                f"    Characters: {', '.join(p.characters_present)}\n"
                f"    Tone: {p.emotional_tone}"
            )
            for p in outline.page_outlines
        )

        style_phrase = get_art_style_phrase(outline.art_style)

        return "\n".join([
            f"Write the complete story for '{outline.title}'.",
            "",
            "ART STYLE — every image_prompt MUST begin with this exact phrase, copied verbatim:",
            f'  "{style_phrase}"',
            "",
            "IMPORTANT — use these EXACT character visual descriptions in every image prompt:",
            char_desc_lines,
            "",
            "Produce exactly the following pages:",
            page_outline_lines,
            "",
            "Plot summary for guiding narrative continuity:",
            outline.plot_summary,
        ])
