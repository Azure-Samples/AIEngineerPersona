"""
LookAndFindActivityExecutor — Fan-out agent (runs in parallel with CharacterGlossaryExecutor).

Receives the approved StoryResponse, inspects the illustrated pages, and uses an LLM to
select 3–5 visually interesting items for the child to search for across the story's pages.
Produces a LookAndFindActivity result forwarded to FinalAssemblyExecutor.
"""

import json
import logging

from agent_framework import ChatAgent, Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..events import ProgressDetailEvent
from ..models import LookAndFindActivity, StoryResponse
from ..prompts import LOOK_AND_FIND_INSTRUCTIONS
from ..utils import extract_json_from_response

logger = logging.getLogger(__name__)


class LookAndFindActivityExecutor(Executor):
    """
    Generates the Look & Find activity page by scanning the approved story's
    illustrated pages and picking 3–5 items for the child to locate.
    """

    def __init__(self) -> None:
        super().__init__(id="look_and_find")
        self._agent = ChatAgent(
            name="LookAndFindActivityAgent",
            instructions=LOOK_AND_FIND_INSTRUCTIONS,
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
        ctx: WorkflowContext[LookAndFindActivity],
    ) -> None:
        logger.info(
            "[LookAndFind] Generating activity page for '%s' (%d pages)",
            story.title,
            len(story.pages),
        )

        prompt = self._build_prompt(story)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="look_and_find",
            detail_type="prompt_sent",
            detail_data={"prompt": prompt, "title": story.title},
        ))

        result = await self._agent.run(prompt)
        raw_json = extract_json_from_response(result.text)
        activity = LookAndFindActivity.model_validate_json(raw_json)

        logger.info(
            "[LookAndFind] Selected %d items to find for '%s'",
            len(activity.items),
            story.title,
        )

        await ctx.add_event(ProgressDetailEvent(
            executor_id="look_and_find",
            detail_type="response_received",
            detail_data={
                "item_count": len(activity.items),
                "items": [
                    {"page": item.page_number, "name": item.item_name}
                    for item in activity.items
                ],
            },
        ))

        await ctx.send_message(activity)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _build_prompt(self, story: StoryResponse) -> str:
        pages_text = "\n\n".join(
            f"--- Page {page.page_number} ---\n"
            f"Text: {page.text}\n"
            f"Scene description: {page.scene_description}\n"
            f"Image prompt: {page.image_prompt}"
            for page in story.pages
        )
        return (
            f"Story title: {story.title}\n\n"
            f"Here are all the story pages with their scene descriptions and image prompts.\n"
            f"Please select 3–5 visually interesting items spread across different pages "
            f"for the Look & Find activity.\n\n"
            f"{pages_text}"
        )
