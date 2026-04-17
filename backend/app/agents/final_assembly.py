"""
FinalAssemblyExecutor — Terminal node in the workflow.

Merges optional bonus content into the StoryResponse and calls ctx.yield_output()
to emit the final story.

Four handler paths depending on which bonus agents were wired:
  fan_in_handler        — both bonus agents ran (fan-in list of bonus content)
  handle_look_and_find  — only Look & Find agent ran
  handle_glossary       — only Character Glossary agent ran
  direct_handler        — neither bonus agent ran (StoryResponse passed directly)

Decision always writes the approved StoryResponse to shared state under "approved_story",
so all handlers except direct_handler can retrieve it from there.
"""

import logging
from typing import Union

from agent_framework import Executor, WorkflowContext, handler

from ..models import CharacterGlossary, LookAndFindActivity, StoryResponse

logger = logging.getLogger(__name__)


class FinalAssemblyExecutor(Executor):
    """
    Merges optional bonus content into the StoryResponse and yields the final output.
    """

    def __init__(self) -> None:
        super().__init__(id="final_assembly")

    # ─── Fan-in path (both bonus agents) ──────────────────────────────────────

    @handler
    async def fan_in_handler(
        self,
        messages: list[Union[LookAndFindActivity, CharacterGlossary]],
        ctx: WorkflowContext[None, StoryResponse],
    ) -> None:
        """Both Look & Find and Character Glossary agents ran."""
        look_and_find: LookAndFindActivity | None = None
        character_glossary: CharacterGlossary | None = None

        for msg in messages:
            if isinstance(msg, LookAndFindActivity):
                look_and_find = msg
            elif isinstance(msg, CharacterGlossary):
                character_glossary = msg

        story = await self._read_story(ctx)
        await self._assemble_and_yield(story, look_and_find, character_glossary, ctx)

    # ─── Single-agent paths ────────────────────────────────────────────────────

    @handler
    async def handle_look_and_find(
        self,
        activity: LookAndFindActivity,
        ctx: WorkflowContext[None, StoryResponse],
    ) -> None:
        """Only Look & Find agent ran."""
        story = await self._read_story(ctx)
        await self._assemble_and_yield(story, activity, None, ctx)

    @handler
    async def handle_glossary(
        self,
        glossary: CharacterGlossary,
        ctx: WorkflowContext[None, StoryResponse],
    ) -> None:
        """Only Character Glossary agent ran."""
        story = await self._read_story(ctx)
        await self._assemble_and_yield(story, None, glossary, ctx)

    # ─── Direct path (no bonus agents) ────────────────────────────────────────

    @handler
    async def direct_handler(
        self,
        story: StoryResponse,
        ctx: WorkflowContext[None, StoryResponse],
    ) -> None:
        """No bonus agents were enabled; yield the StoryResponse as-is."""
        await self._assemble_and_yield(story, None, None, ctx)

    # ─── Internal helpers ──────────────────────────────────────────────────────

    async def _read_story(self, ctx: WorkflowContext) -> StoryResponse:
        """Read the approved StoryResponse from shared state."""
        story_json = await ctx.get_shared_state("approved_story")
        if not story_json:
            raise RuntimeError(
                "FinalAssemblyExecutor: 'approved_story' not found in shared state. "
                "DecisionExecutor must run before FinalAssemblyExecutor."
            )
        return StoryResponse.model_validate_json(story_json)

    async def _assemble_and_yield(
        self,
        story: StoryResponse,
        look_and_find: LookAndFindActivity | None,
        character_glossary: CharacterGlossary | None,
        ctx: WorkflowContext,
    ) -> None:
        final = story.model_copy(update={
            "look_and_find": look_and_find,
            "character_glossary": character_glossary,
        })

        logger.info(
            "[FinalAssembly] Yielding final story '%s' "
            "(look_and_find=%s, character_glossary=%s)",
            final.title,
            look_and_find is not None,
            character_glossary is not None,
        )

        await ctx.yield_output(final)
