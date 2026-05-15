"""
ArtDirectorExecutor — Third node in the workflow.

Receives a StoryDraft and generates one illustration per page using the
Azure OpenAI image generation API (DALL-E / gpt-image-1).
Each page's image_url is populated before the updated draft is sent downstream.

Also handles partial-image revision signals (ImageRevisionSignal) from
DecisionExecutor: regenerates ONLY the slots flagged by the StoryReviewer,
preserving every other slot's existing image_url.
"""

import asyncio
import base64
import json
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
from ..signals import ImageRevisionSignal

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

        session_id = self._resolve_session_id(ctx)
        revision_round = ctx.get_state("revision_count", default=0) or 0
        character_descriptions = self._read_character_descriptions(ctx)

        # ── Derive style reference from the first page's prompt ───────────────
        style_ref = draft.pages[0].image_prompt if draft.pages else ""
        style_hint = self._style_hint(style_ref)

        # Collect character names from all pages (deduplicated)
        all_chars: list[str] = []
        seen: set[str] = set()
        for page in draft.pages:
            for c in page.characters_present:
                if c not in seen:
                    seen.add(c)
                    all_chars.append(c)

        # Build the cover + "The End" prompts and persist them onto the draft
        # so partial revisions can rebuild them without re-running this logic.
        cover_prompt = self._build_cover_prompt(
            title=draft.title,
            character_names=all_chars,
            character_descriptions=character_descriptions,
            style_hint=style_hint,
        )
        end_prompt = self._build_the_end_prompt(style_hint=style_hint)
        draft.cover_image_prompt = cover_prompt
        draft.the_end_image_prompt = end_prompt

        # ── Signal start of this batch (serves as revision-round pivot) ───────
        await ctx.add_event(ProgressDetailEvent(
            executor_id="art_director",
            detail_type="images_batch_started",
            detail_data={
                "total_images": total_images,
                "total_pages": total,
                "partial": False,
                "revision_round": revision_round,
            },
        ))

        # Ordered task list: (page_number, label, prompt)
        # Cover=0, story pages 1..N, The End=N+1
        tasks = [
            (0,          "Cover",     cover_prompt),
            *((p.page_number, f"Page {p.page_number}", p.image_prompt) for p in draft.pages),
            (total + 1,  "The End",   end_prompt),
        ]

        # Emit image_queued for every task upfront so the UI can show all slots
        for page_number, label, _ in tasks:
            await ctx.add_event(ProgressDetailEvent(
                executor_id="art_director",
                detail_type="image_queued",
                detail_data={"page_number": page_number, "total_pages": total, "label": label},
            ))

        semaphore = asyncio.Semaphore(_CONCURRENT_IMAGE_LIMIT)
        await asyncio.gather(*(
            self._generate_one(
                ctx=ctx, draft=draft, total=total, session_id=session_id,
                revision_round=revision_round, semaphore=semaphore,
                page_number=pn, label=lbl, prompt=prompt,
            )
            for pn, lbl, prompt in tasks
        ))

        ctx.set_state("illustrated_draft", draft.model_dump_json())
        logger.info("[ArtDirector] All illustrations complete for '%s'", draft.title)
        await ctx.send_message(draft)

    @handler
    async def handle_image_revision(
        self,
        signal: ImageRevisionSignal,
        ctx: WorkflowContext[StoryDraft],
    ) -> None:
        """Partial-image revision: regenerate ONLY the slots listed in the signal.

        The full draft is loaded from shared state (it was persisted by the
        most recent ``handle_draft`` or prior revision round). Only the
        affected slots' ``image_url`` fields are touched; every other page
        keeps its existing image.
        """
        targets = list(signal.targets)
        if not targets:
            # Defensive: DecisionExecutor already guards against this, but
            # if a stale or hand-constructed signal slips through, fall back
            # to forwarding the existing draft unchanged so the workflow
            # doesn't stall.
            logger.warning(
                "[ArtDirector] Received ImageRevisionSignal with no targets — "
                "forwarding existing draft unchanged."
            )
            draft = self._load_draft_or_raise(ctx)
            await ctx.send_message(draft)
            return

        draft = self._load_draft_or_raise(ctx)
        total = len(draft.pages)
        session_id = self._resolve_session_id(ctx)

        # Mirror the orchestrator pattern: increment revision_count when
        # this branch handles the revision (the orchestrator path is skipped
        # on images-only revisions, so it can't increment for us).
        revision_count = (ctx.get_state("revision_count", default=0) or 0) + 1
        ctx.set_state("revision_count", revision_count)

        logger.info(
            "[ArtDirector] Image-only revision round %d for '%s' — regenerating %d slot(s): %s",
            revision_count,
            draft.title,
            len(targets),
            [t.label for t in targets],
        )

        # ── Signal partial batch (round pivot for the frontend) ──────────────
        await ctx.add_event(ProgressDetailEvent(
            executor_id="art_director",
            detail_type="images_batch_started",
            detail_data={
                "total_images": len(targets),
                "total_pages": total,
                "partial": True,
                "affected_slots": [t.slot for t in targets],
                "revision_round": revision_count,
            },
        ))

        # Build per-slot prompts. For is_retry_only targets (missing-image
        # synthetic issues), reuse the original prompt verbatim — appending
        # "image was not generated" as a correction would be noise.
        tasks: list[tuple[int, str, str]] = []
        for target in targets:
            original_prompt = self._original_prompt_for_slot(draft, target.slot, total)
            if original_prompt is None:
                logger.warning(
                    "[ArtDirector] No original prompt found for slot %d (%s) — skipping.",
                    target.slot, target.label,
                )
                continue
            if target.is_retry_only or not target.revision_notes.strip():
                refined_prompt = original_prompt
            else:
                refined_prompt = self._refine_prompt(original_prompt, target.revision_notes)
            tasks.append((target.slot, target.label, refined_prompt))

        if not tasks:
            # Every target had a missing original prompt — extremely unusual
            # but guard against an infinite no-op loop.
            logger.warning(
                "[ArtDirector] Image-only revision had no resolvable targets — "
                "forwarding existing draft unchanged."
            )
            await ctx.send_message(draft)
            return

        for page_number, label, _ in tasks:
            await ctx.add_event(ProgressDetailEvent(
                executor_id="art_director",
                detail_type="image_queued",
                detail_data={"page_number": page_number, "total_pages": total, "label": label},
            ))

        semaphore = asyncio.Semaphore(_CONCURRENT_IMAGE_LIMIT)
        await asyncio.gather(*(
            self._generate_one(
                ctx=ctx, draft=draft, total=total, session_id=session_id,
                revision_round=revision_count, semaphore=semaphore,
                page_number=pn, label=lbl, prompt=prompt,
            )
            for pn, lbl, prompt in tasks
        ))

        ctx.set_state("illustrated_draft", draft.model_dump_json())
        logger.info(
            "[ArtDirector] Partial revision complete (%d slot(s)) — forwarding draft.",
            len(tasks),
        )
        await ctx.send_message(draft)

    # ─── Internal helpers ────────────────────────────────────────────────────

    async def _generate_one(
        self,
        *,
        ctx: WorkflowContext,
        draft: StoryDraft,
        total: int,
        session_id: str,
        revision_round: int,
        semaphore: asyncio.Semaphore,
        page_number: int,
        label: str,
        prompt: str,
    ) -> None:
        """Generate one image slot, emit lifecycle events, write the URL onto the draft.

        Shared by both the full-pass handler and the partial-revision handler so
        the lifecycle event payloads stay identical.
        """
        revision_suffix = f".r{revision_round}" if revision_round else ""
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

                label_slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or f"image_{page_number}"
                filename = f"{label_slug}{revision_suffix}.png"
                image_url = save_draft_image(session_id, filename, png_bytes)

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

    @staticmethod
    def _style_hint(style_ref: str) -> str:
        return style_ref[:300] if len(style_ref) > 300 else style_ref

    @staticmethod
    def _build_cover_prompt(
        *,
        title: str,
        character_names: list[str],
        character_descriptions: dict[str, str],
        style_hint: str,
    ) -> str:
        # Build a per-character description block for the cover prompt so the
        # image model has full visual definitions and can't invent extra
        # animals/creatures. Falls back to bare names if the outline didn't
        # provide descriptions.
        if character_descriptions:
            lines = []
            for name in character_names[:6]:
                desc = character_descriptions.get(name)
                if desc:
                    lines.append(f"  - {name}: {desc}")
                else:
                    lines.append(f"  - {name}")
            chars_block = "\n".join(lines)
        else:
            chars_block = ", ".join(character_names[:6]) if character_names else "the main characters"

        return (
            f"A beautiful, full-bleed children's book cover illustration for a story titled "
            f'"{title}".\n\n'
            f"The cover MUST feature ONLY the following characters, drawn exactly as described:\n"
            f"{chars_block}\n\n"
            f"Compose them together in a warm, inviting scene that captures the spirit of the story. "
            f"Use the same artistic style as the interior pages: {style_hint}. "
            f"The image should feel like a classic picture book cover — colourful, engaging, "
            f"and suitable for young children. "
            f"Do NOT include any other characters, animals, or living creatures of any kind — "
            f"no extra mice, cats, birds, bunnies, bystanders, or background figures beyond the "
            f"characters listed above. "
            f"Do NOT include any text or lettering in the image."
        )

    @staticmethod
    def _build_the_end_prompt(*, style_hint: str) -> str:
        return (
            f'A beautiful children\'s book closing page illustration with the words "The End" '
            f"rendered in large, elegant, decorative hand-lettered calligraphy as the focal point. "
            f"The lettering should be warm and celebratory. Surround the text with soft, colourful "
            f"illustrated motifs (stars, flowers, swirls, or gentle sparkles) consistent with the "
            f"visual style of the story: {style_hint}. "
            f"The overall feeling should be warm, satisfying, and conclusive. "
            f"The text 'The End' must be clearly legible and the dominant element of the composition."
        )

    @staticmethod
    def _refine_prompt(original_prompt: str, revision_notes: str) -> str:
        """Wrap the reviewer's notes as positive corrections on top of the original prompt.

        Image-generation models respond better to positive constraints ("the
        scarf must be blue") than to negative or retrospective wording ("the
        scarf was green; fix it"). The notes have already been deduplicated
        and grouped per slot by the reviewer aggregator.
        """
        notes = revision_notes.strip()
        if not notes:
            return original_prompt
        # Ensure each correction is a bullet line for the model.
        bulleted = "\n".join(
            line if line.lstrip().startswith("-") else f"- {line.strip()}"
            for line in notes.splitlines()
            if line.strip()
        )
        return (
            f"{original_prompt}\n\n"
            f"CORRECTIONS required from the story reviewer — these MUST be reflected in the "
            f"regenerated image. Keep every other requirement from the original prompt intact.\n"
            f"{bulleted}"
        )

    @staticmethod
    def _original_prompt_for_slot(draft: StoryDraft, slot: int, total: int) -> str | None:
        if slot == 0:
            return draft.cover_image_prompt
        if slot == total + 1:
            return draft.the_end_image_prompt
        if 1 <= slot <= total:
            return draft.pages[slot - 1].image_prompt
        return None

    @staticmethod
    def _resolve_session_id(ctx) -> str:  # noqa: ANN001
        return ctx.get_state("session_id", default=None) or uuid.uuid4().hex

    @staticmethod
    def _read_character_descriptions(ctx) -> dict[str, str]:  # noqa: ANN001
        # Canonical character descriptions (set by Orchestrator). These pin the
        # cover's character roster — without them the image model invents
        # extra creatures on the cover (e.g. a mouse and a cat that don't
        # exist anywhere in the story).
        outline_json = ctx.get_state("outline", default=None)
        if not outline_json:
            return {}
        try:
            return json.loads(outline_json).get("character_descriptions", {}) or {}
        except Exception:
            return {}

    @staticmethod
    def _load_draft_or_raise(ctx) -> StoryDraft:  # noqa: ANN001
        draft_json = ctx.get_state("illustrated_draft", default=None)
        if not draft_json:
            raise RuntimeError(
                "ArtDirectorExecutor: 'illustrated_draft' not found in state. "
                "handle_image_revision can only run after an initial illustrated pass."
            )
        return StoryDraft.model_validate_json(draft_json)
