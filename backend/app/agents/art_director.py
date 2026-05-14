"""
ArtDirectorExecutor — Third node in the workflow.

Receives a StoryDraft and generates one illustration per page using the
Azure OpenAI image generation API (DALL-E / gpt-image-1).
Each page's image_url is populated before the updated draft is sent downstream.
"""

import asyncio
import base64
import logging
import re
import uuid

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from agent_framework import Executor, WorkflowContext, handler

from ..config import settings
from ..demo_stories import save_draft_image
from ..models import StoryDraft
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

        # Per-generation session id (set by StoryGenerator → Orchestrator).
        # Falls back to a fresh uuid so revision rounds and ad-hoc invocations
        # without an upstream session still get isolated draft folders.
        session_id = (
            ctx.get_state("session_id", default=None) or uuid.uuid4().hex
        )

        # Revision round (0 for the initial pass, 1+ after StoryReviewer asks
        # for changes).  Folded into image filenames so a revision's images
        # don't overwrite the originals in storage — that lets the saved
        # event history accurately replay every round's illustrations.
        revision_round = ctx.get_state("revision_count", default=0) or 0
        revision_suffix = f".r{revision_round}" if revision_round else ""

        # Canonical character descriptions (set by Orchestrator). These pin the
        # cover's character roster — without them the image model invents
        # extra creatures on the cover (e.g. a mouse and a cat that don't
        # exist anywhere in the story).
        character_descriptions: dict[str, str] = {}
        outline_json = ctx.get_state("outline", default=None)
        if outline_json:
            try:
                import json as _json
                character_descriptions = _json.loads(outline_json).get(
                    "character_descriptions", {}
                ) or {}
            except Exception:
                pass

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

        # Build a per-character description block for the cover prompt so the
        # image model has full visual definitions and can't invent extra
        # animals/creatures. Falls back to bare names if the outline didn't
        # provide descriptions.
        if character_descriptions:
            cover_chars_block_lines = []
            for name in all_chars[:6]:
                desc = character_descriptions.get(name)
                if desc:
                    cover_chars_block_lines.append(f"  - {name}: {desc}")
                else:
                    cover_chars_block_lines.append(f"  - {name}")
            cover_chars_block = "\n".join(cover_chars_block_lines)
        else:
            cover_chars_block = chars_str

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
            f'"{draft.title}".\n\n'
            f"The cover MUST feature ONLY the following characters, drawn exactly as described:\n"
            f"{cover_chars_block}\n\n"
            f"Compose them together in a warm, inviting scene that captures the spirit of the story. "
            f"Use the same artistic style as the interior pages: {style_hint}. "
            f"The image should feel like a classic picture book cover — colourful, engaging, "
            f"and suitable for young children. "
            f"Do NOT include any other characters, animals, or living creatures of any kind — "
            f"no extra mice, cats, birds, bunnies, bystanders, or background figures beyond the "
            f"characters listed above. "
            f"Do NOT include any text or lettering in the image."
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
                    png_bytes = base64.b64decode(b64)

                    # Persist to disk under the session's drafts folder so SSE
                    # frames stay tiny (a URL, not a 1MB base64 blob) and the
                    # frontend can render via plain <img src="/api/drafts/...">.
                    # The revision suffix (e.g. ".r1") preserves earlier rounds
                    # so the saved event history can show every iteration.
                    label_slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or f"image_{page_number}"
                    filename = f"{label_slug}{revision_suffix}.png"
                    image_url = save_draft_image(session_id, filename, png_bytes)

                    # Store on the appropriate model field
                    if page_number == 0:
                        draft.cover_image_url = image_url
                    elif page_number == total + 1:
                        draft.the_end_image_url = image_url
                    else:
                        draft.pages[page_number - 1].image_url = image_url

                    logger.info("[ArtDirector] Completed image: %s -> %s", label, image_url)
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
        ctx.set_state("illustrated_draft", draft.model_dump_json())

        logger.info("[ArtDirector] All illustrations complete for '%s'", draft.title)
        await ctx.send_message(draft)
