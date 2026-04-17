"""
CharacterGlossaryExecutor — Fan-out agent (runs in parallel with LookAndFindActivityExecutor).

Receives the approved StoryResponse and the story outline from shared state, then uses an
LLM to write a child-friendly glossary entry for every character in the story.
Produces a CharacterGlossary result forwarded to FinalAssemblyExecutor.
"""

import json
import logging

from agent_framework import ChatAgent, Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..events import ProgressDetailEvent
from ..models import CharacterGlossary, StoryOutline, StoryResponse
from ..prompts import CHARACTER_GLOSSARY_INSTRUCTIONS
from ..utils import extract_json_from_response

logger = logging.getLogger(__name__)


class CharacterGlossaryExecutor(Executor):
    """
    Generates a "Meet the Characters" glossary page by writing short,
    child-friendly descriptions for every character in the story.
    """

    def __init__(self) -> None:
        super().__init__(id="character_glossary")
        self._agent = ChatAgent(
            name="CharacterGlossaryAgent",
            instructions=CHARACTER_GLOSSARY_INSTRUCTIONS,
            chat_client=AzureOpenAIChatClient(
                endpoint=settings.foundry_project_endpoint,
                deployment_name=settings.foundry_model_deployment_name,
                credential=DefaultAzureCredential(),
            ),
        )

    @handler
    async def handle_story(
        self,
        story: StoryResponse,
        ctx: WorkflowContext[CharacterGlossary],
    ) -> None:
        logger.info(
            "[CharacterGlossary] Generating glossary for '%s'",
            story.title,
        )

        # Pull character descriptions from the outline stored in shared state
        character_descriptions: dict[str, str] = {}
        outline_json = await ctx.get_shared_state("outline")
        if outline_json:
            try:
                outline = StoryOutline.model_validate_json(outline_json)
                character_descriptions = outline.character_descriptions
            except Exception:
                logger.warning("[CharacterGlossary] Could not parse outline from shared state")

        prompt = self._build_prompt(story, character_descriptions)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="character_glossary",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "title": story.title},
        ))

        result = await self._agent.run(prompt)
        raw_json = extract_json_from_response(result.text)
        glossary = CharacterGlossary.model_validate_json(raw_json)

        logger.info(
            "[CharacterGlossary] Generated %d glossary entries for '%s'",
            len(glossary.entries),
            story.title,
        )

        await ctx.add_event(ProgressDetailEvent(
            executor_id="character_glossary",
            detail_type="response_received",
            detail_data={
                "entry_count": len(glossary.entries),
                "characters": [e.name for e in glossary.entries],
            },
        ))

        await ctx.send_message(glossary)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_prompt(
        self,
        story: StoryResponse,
        character_descriptions: dict[str, str],
    ) -> str:
        char_block = ""
        if character_descriptions:
            lines = [f"  - {name}: {desc}" for name, desc in character_descriptions.items()]
            char_block = "Visual character descriptions from the illustrator:\n" + "\n".join(lines) + "\n\n"

        pages_text = "\n\n".join(
            f"Page {p.page_number} (characters present: {', '.join(p.characters_present)}): {p.text}"
            for p in story.pages
        )

        return (
            f"Story title: {story.title}\n"
            f"Moral: {story.moral_summary}\n\n"
            f"{char_block}"
            f"Story pages:\n{pages_text}\n\n"
            f"Please write a child-friendly glossary entry for every named character who appears in the story."
        )
