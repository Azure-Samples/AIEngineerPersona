"""
StoryArchitectExecutor — Second node in the workflow.

Receives a StoryOutline from the OrchestratorExecutor and writes the full
narrative text + image prompts for every page, producing a StoryDraft.
"""

import logging

from agent_framework import ChatAgent, Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..models import StoryOutline, StoryDraft
from ..prompts import STORY_ARCHITECT_INSTRUCTIONS
from ..utils import extract_json_from_response
from ..events import ProgressDetailEvent

logger = logging.getLogger(__name__)


class StoryArchitectExecutor(Executor):
    """
    Writes the complete story text and image prompts for each page based
    on the outline produced by the OrchestratorExecutor.
    """

    def __init__(self) -> None:
        super().__init__(id="story_architect")
        self._agent = ChatAgent(
            name="StoryArchitectAgent",
            instructions=STORY_ARCHITECT_INSTRUCTIONS,
            chat_client=AzureOpenAIChatClient(
                endpoint=settings.foundry_project_endpoint,
                deployment_name=settings.foundry_model_deployment_name,
                credential=DefaultAzureCredential(),
            ),
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
        await ctx.set_shared_state("outline", outline.model_dump_json())

        prompt = self._build_prompt(outline)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_architect",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "title": outline.title, "page_count": outline.target_pages},
        ))

        result = await self._agent.run(prompt)
        raw_json = extract_json_from_response(result.text)
        draft = StoryDraft.model_validate_json(raw_json)

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

        return "\n".join([
            f"Write the complete story for '{outline.title}'.",
            "",
            "IMPORTANT — use these EXACT character visual descriptions in every image prompt:",
            char_desc_lines,
            "",
            "Produce exactly the following pages:",
            page_outline_lines,
            "",
            "Plot summary for guiding narrative continuity:",
            outline.plot_summary,
            "",
            "Return a complete StoryDraft JSON object. "
            "Each page must include: page_number, text, scene_description, "
            "characters_present, emotional_tone, and image_prompt.",
        ])
