"""
ArtDirectorExecutor — Third node in the workflow.

Receives a StoryDraft and generates one illustration per page using the
Azure OpenAI image generation API (DALL-E / gpt-image-1).
Each page's image_url is populated before the updated draft is sent downstream.
"""

import asyncio
import logging

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from agent_framework import Executor, WorkflowContext, handler

from ..config import settings
from ..models import StoryDraft
from ..utils import extract_json_from_response
from ..events import ProgressDetailEvent

logger = logging.getLogger(__name__)

# Azure Cognitive Services token scope for Azure OpenAI
_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

# Max simultaneous image generation requests (avoids 429 rate-limit errors)
_CONCURRENT_IMAGE_LIMIT = 5


class ArtDirectorExecutor(Executor):
    """
    For each page in the story draft, calls the Azure OpenAI image generation
    API using the page's image_prompt and stores the resulting URL on the page.
    """

    def __init__(self) -> None:
        super().__init__(id="art_director")
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), _COGNITIVE_SERVICES_SCOPE
        )
        self._oai_client = AsyncAzureOpenAI(
            azure_endpoint=settings.foundry_project_endpoint,
            azure_ad_token_provider=token_provider,
            api_version="2024-02-01",
        )

    @handler
    async def handle_draft(
        self,
        draft: StoryDraft,
        ctx: WorkflowContext[StoryDraft],
    ) -> None:
        total = len(draft.pages)
        total_images = total + 2  # story pages + cover + the end
        logger.info(
            "[ArtDirector] Queuing %d illustrations (max %d concurrent) for '%s'",
            total_images,
            _CONCURRENT_IMAGE_LIMIT,
            draft.title,
        )

        # ── Derive style reference from the first page's prompt ───────────────
        style_ref = draft.pages[0].image_prompt if draft.pages else ""
        style_hint = style_ref[:300] if len(style_ref) > 300 else style_ref

        # Collect character names from all pages (deduplicated)
        all_chars: list[str] = []
        seen: set[str] = set()
        for page in draft.pages:
            for c in page.characters_present:
                if c not in seen:
                    seen.add(c)
                    all_chars.append(c)
        chars_str = ", ".join(all_chars[:6]) if all_chars else "the main characters"

        # ── Signal start of this batch (serves as revision-round pivot) ───────
        await ctx.add_event(ProgressDetailEvent(
            executor_id="art_director",
            detail_type="images_batch_started",
            detail_data={"total_images": total_images, "total_pages": total},
        ))

        # ── Build the full task list: (page_number, label, prompt, setter) ────
        # Each entry is aligned so we can emit queued events upfront then
        # process them one-by-one as semaphore slots become available.

        cover_prompt = (
            f"A beautiful, full-bleed children's book cover illustration for a story titled "
            f'"{draft.title}". The scene should prominently feature {chars_str} in a warm, '
            f"inviting composition that captures the spirit of the story. "
            f"Use the same artistic style as the interior pages: {style_hint}. "
            f"The image should feel like a classic picture book cover — colourful, engaging, "
            f"and suitable for young children. Do NOT include any text or lettering in the image."
        )
        end_prompt = (
            f'A beautiful children\'s book closing page illustration with the words "The End" '
            f"rendered in large, elegant, decorative hand-lettered calligraphy as the focal point. "
            f"The lettering should be warm and celebratory. Surround the text with soft, colourful "
            f"illustrated motifs (stars, flowers, swirls, or gentle sparkles) consistent with the "
            f"visual style of the story: {style_hint}. "
            f"The overall feeling should be warm, satisfying, and conclusive. "
            f"The text 'The End' must be clearly legible and the dominant element of the composition."
        )

        # Ordered list of (page_number, label, prompt)
        # Cover=0, story pages 1..N, The End=N+1
        tasks = [
            (0,          "Cover",     cover_prompt),
            *((p.page_number, f"Page {p.page_number}", p.image_prompt) for p in draft.pages),
            (total + 1,  "The End",   end_prompt),
        ]

        # Emit image_queued for every task immediately so the UI can show all slots
        for page_number, label, _ in tasks:
            await ctx.add_event(ProgressDetailEvent(
                executor_id="art_director",
                detail_type="image_queued",
                detail_data={"page_number": page_number, "total_pages": total, "label": label},
            ))

        # ── Semaphore-limited generation ──────────────────────────────────────
        semaphore = asyncio.Semaphore(_CONCURRENT_IMAGE_LIMIT)

        async def _run_one(page_number: int, label: str, prompt: str) -> None:
            async with semaphore:
                logger.info("[ArtDirector] Starting image: %s", label)
                await ctx.add_event(ProgressDetailEvent(
                    executor_id="art_director",
                    detail_type="image_started",
                    detail_data={"page_number": page_number, "total_pages": total, "label": label, "prompt": prompt},
                ))
                try:
                    response = await self._oai_client.images.generate(
                        model=settings.foundry_image_model_deployment_name,
                        prompt=prompt,
                        size="1024x1024",
                        quality="high",
                        n=1,
                        output_format="png",
                    )
                    b64 = response.data[0].b64_json
                    image_url = f"data:image/png;base64,{b64}"

                    # Store on the appropriate model field
                    if page_number == 0:
                        draft.cover_image_url = image_url
                    elif page_number == total + 1:
                        draft.the_end_image_url = image_url
                    else:
                        draft.pages[page_number - 1].image_url = image_url

                    logger.info("[ArtDirector] Completed image: %s", label)
                    await ctx.add_event(ProgressDetailEvent(
                        executor_id="art_director",
                        detail_type="image_completed",
                        detail_data={"page_number": page_number, "total_pages": total, "label": label, "image_url": image_url},
                    ))
                except Exception as exc:
                    logger.warning("[ArtDirector] Image failed for %s: %s", label, exc)
                    await ctx.add_event(ProgressDetailEvent(
                        executor_id="art_director",
                        detail_type="image_failed",
                        detail_data={"page_number": page_number, "total_pages": total, "label": label, "error": str(exc)},
                    ))

        await asyncio.gather(*(_run_one(pn, lbl, prompt) for pn, lbl, prompt in tasks))

        # Store the illustrated draft in workflow state so the DecisionExecutor
        # can assemble the final StoryResponse without re-passing the whole draft.
        await ctx.set_shared_state("illustrated_draft", draft.model_dump_json())

        logger.info("[ArtDirector] All illustrations complete for '%s'", draft.title)
        await ctx.send_message(draft)
