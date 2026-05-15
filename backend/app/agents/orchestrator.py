"""
OrchestratorExecutor — First node in the workflow.

Accepts the initial StoryRequest from the user (or a RevisionSignal from the
DecisionExecutor on subsequent loops) and produces a StoryOutline for the
StoryArchitectExecutor.
"""

import logging
from typing import Optional

from agent_framework import Agent, Executor, WorkflowContext, handler
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..models import StoryRequest, StoryOutline, StoryOutlineDraft
from ..prompts import ORCHESTRATOR_INSTRUCTIONS
from ..signals import RevisionSignal
from ..events import ProgressDetailEvent

logger = logging.getLogger(__name__)


class OrchestratorExecutor(Executor):
    """
    Creates the initial story outline and revises it when the StoryReviewer
    sends back feedback.
    """

    def __init__(self) -> None:
        super().__init__(id="orchestrator")
        self._agent = Agent(
            client=OpenAIChatClient(
                model=settings.foundry_model_deployment_name,
                azure_endpoint=settings.foundry_project_endpoint,
                credential=DefaultAzureCredential(),
            ),
            instructions=ORCHESTRATOR_INSTRUCTIONS,
            name="OrchestratorAgent",
        )

    # ─── Initial run ──────────────────────────────────────────────────────────

    @handler
    async def handle_initial_request(
        self,
        request: StoryRequest,
        ctx: WorkflowContext[StoryOutline],
    ) -> None:
        """Called once with the user's form input on the very first run."""
        logger.info("[Orchestrator] Received initial story request for: %s", request.main_character)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="orchestrator",
            detail_type="executor_started",
            detail_data={
                "mode": "initial",
                "main_character": request.main_character,
                "supporting_characters": request.supporting_characters or [],
                "setting": request.setting,
                "moral": request.moral,
                "main_problem": request.main_problem,
            },
        ))

        # Persist the original request so revision runs can reference it
        ctx.set_state("story_request", request.model_dump_json())
        ctx.set_state("revision_count", 0)
        # ArtDirector reads this to scope on-disk draft images per generation.
        if request.session_id:
            ctx.set_state("session_id", request.session_id)

        outline = await self._create_outline(request, revision_instructions=None, ctx=ctx)
        logger.info("[Orchestrator] Outline created: '%s' (%d pages)", outline.title, outline.target_pages)

        await ctx.send_message(outline)

    # ─── Revision run ─────────────────────────────────────────────────────────

    @handler
    async def handle_revision(
        self,
        signal: RevisionSignal,
        ctx: WorkflowContext[StoryOutline],
    ) -> None:
        """Called by DecisionExecutor when the StoryReviewer rejects the story."""
        revision_count = (ctx.get_state("revision_count") or 0) + 1
        ctx.set_state("revision_count", revision_count)
        logger.info("[Orchestrator] Starting revision round %d", revision_count)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="orchestrator",
            detail_type="revision_started",
            detail_data={
                "revision_number": revision_count,
                "revision_instructions": signal.revision_instructions,
            },
        ))

        request_json = ctx.get_state("story_request")
        request = StoryRequest.model_validate_json(request_json)

        outline = await self._create_outline(request, revision_instructions=signal.revision_instructions, ctx=ctx)
        logger.info("[Orchestrator] Revised outline ready: '%s'", outline.title)

        await ctx.send_message(outline)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    async def _create_outline(
        self,
        request: StoryRequest,
        revision_instructions: Optional[str],
        ctx: WorkflowContext,
    ) -> StoryOutline:
        characters_str = ", ".join(request.supporting_characters) if request.supporting_characters else "none"
        additional = request.additional_details or "No additional details provided."

        prompt_parts = [
            "Create a story outline based on these parameters:",
            f"- Main character: {request.main_character}",
            f"- Supporting characters: {characters_str}",
            f"- Setting: {request.setting}",
            f"- Moral of the story: {request.moral}",
            f"- Main problem: {request.main_problem}",
            f"- Additional details: {additional}",
        ]

        if revision_instructions:
            prompt_parts += [
                "",
                "REVISION FEEDBACK FROM STORY REVIEWER — please address ALL of these points:",
                revision_instructions,
                "",
                "Produce an improved outline that fixes every issue listed above.",
            ]

        prompt = "\n".join(prompt_parts)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="orchestrator",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "is_revision": revision_instructions is not None},
        ))

        result = await self._agent.run(
            prompt,
            options={
                "response_format": StoryOutlineDraft,
                # gpt-5.x is a reasoning model — give the response budget enough
                # headroom for BOTH internal reasoning tokens AND the structured
                # JSON output. Without an explicit cap the SDK default leaves
                # only a few hundred output tokens after reasoning, which
                # truncates the JSON mid-string and throws Pydantic
                # `Invalid JSON: EOF while parsing` errors. 16k is comfortably
                # above the largest legitimate StoryOutlineDraft we've seen.
                "max_tokens": 16000,
            },
        )
        # The model emits a StoryOutlineDraft (character_descriptions is a list
        # of {name, description}). Convert to StoryOutline (dict[str,str]) so
        # downstream executors keep their existing dict-based access pattern.
        draft: StoryOutlineDraft = result.value
        outline = StoryOutline(
            title=draft.title,
            target_pages=draft.target_pages,
            character_descriptions={cd.name: cd.description for cd in draft.character_descriptions},
            plot_summary=draft.plot_summary,
            page_outlines=draft.page_outlines,
            revision_instructions=revision_instructions,
            art_style=request.art_style,
        )

        await ctx.add_event(ProgressDetailEvent(
            executor_id="orchestrator",
            detail_type="response_received",
            detail_data={
                "title": outline.title,
                "page_count": outline.target_pages,
                "plot_summary": outline.plot_summary,
                "characters": list(outline.character_descriptions.keys()),
            },
        ))

        return outline

