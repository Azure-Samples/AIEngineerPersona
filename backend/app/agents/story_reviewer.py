"""
StoryReviewerExecutor — Fourth node in the workflow.

Receives the fully illustrated StoryDraft and performs a multi-call quality
review, then aggregates the per-call results into a single ReviewResult that
the DecisionExecutor uses to either approve or request revisions.

Architecture (replaces the legacy single mega-call design):

    StoryDraft
        │
        ├── per-page reviewer × N (one image, scoped prompt)
        ├── cover reviewer (one image, scoped prompt)
        ├── "The End" reviewer (one image, scoped prompt)
        ├── story-text reviewer (text only, no images)
        └── cross-page consistency reviewer (all character images, narrow prompt)
                │
                ▼  asyncio.gather, behind a semaphore
        per-call results
                │
                ▼  deterministic aggregator (no extra LLM call)
        ReviewResult  → DecisionExecutor

Why fan out: a single mega-call (one prompt with ~12 images + ~12 pages of
metadata + a 5-category checklist) consistently primed the vision model to
hallucinate non-existent visual defects ("opaque rectangles obscuring
characters"). Splitting the work into focused, narrow-scope calls reduces
per-call surface area and gives each call a job small enough that "ZERO
issues" is a believable answer.
"""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

from agent_framework import (
    Agent,
    Content,
    Executor,
    Message,
    WorkflowContext,
    handler,
)
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..events import ProgressDetailEvent
from ..models import (
    CrossPageConsistencyResult,
    ImageRevisionTarget,
    PageReviewResult,
    ReviewIssue,
    ReviewResult,
    StoryDraft,
    StoryPage,
    StoryTextReviewResult,
)
from ..prompts import (
    COVER_REVIEWER_INSTRUCTIONS,
    CROSS_PAGE_CONSISTENCY_INSTRUCTIONS,
    PER_PAGE_REVIEWER_INSTRUCTIONS,
    STORY_TEXT_REVIEWER_INSTRUCTIONS,
    THE_END_REVIEWER_INSTRUCTIONS,
)
from ..storage import get_backend
from ..utils import record_llm_usage

logger = logging.getLogger(__name__)


# Severity thresholds preserved from the legacy single-call reviewer policy
# (see prompts.py:261-267 in the legacy STORY_REVIEWER_INSTRUCTIONS).
_REJECT_ON_HIGH = 1            # 1+ high-severity issue → reject
_REJECT_ON_MEDIUM = 4          # 4+ medium-severity issues → reject


class StoryReviewerExecutor(Executor):
    """
    Reviews the illustrated story by fanning out into N+3 focused LLM calls
    (per-page + cover + "The End" + story-text + cross-page consistency)
    and aggregates the per-call results into a single ReviewResult.
    """

    def __init__(self) -> None:
        super().__init__(id="story_reviewer")
        self._per_page_agent = self._build_agent(
            PER_PAGE_REVIEWER_INSTRUCTIONS, "PerPageReviewerAgent"
        )
        self._cover_agent = self._build_agent(
            COVER_REVIEWER_INSTRUCTIONS, "CoverReviewerAgent"
        )
        self._the_end_agent = self._build_agent(
            THE_END_REVIEWER_INSTRUCTIONS, "TheEndReviewerAgent"
        )
        self._text_agent = self._build_agent(
            STORY_TEXT_REVIEWER_INSTRUCTIONS, "StoryTextReviewerAgent"
        )
        self._cross_page_agent = self._build_agent(
            CROSS_PAGE_CONSISTENCY_INSTRUCTIONS, "CrossPageConsistencyAgent"
        )

        # Bursting through Azure OpenAI RPM limits would amplify retries and
        # latency; cap the number of concurrent reviewer subcalls.
        self._semaphore = asyncio.Semaphore(
            max(1, settings.story_reviewer_max_concurrent_calls)
        )

    @staticmethod
    def _build_agent(instructions: str, name: str) -> Agent:
        return Agent(
            client=OpenAIChatClient(
                model=settings.foundry_model_deployment_name,
                azure_endpoint=settings.foundry_project_endpoint,
                credential=DefaultAzureCredential(),
            ),
            instructions=instructions,
            name=name,
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

        # ── Resolve shared state ──────────────────────────────────────────
        character_descriptions: dict[str, str] = {}
        plot_summary: str = ""
        outline_json = ctx.get_state("outline")
        if outline_json:
            try:
                outline_data = json.loads(outline_json)
                character_descriptions = outline_data.get("character_descriptions", {})
                plot_summary = outline_data.get("plot_summary", "") or ""
            except Exception:
                pass  # graceful degradation — review still proceeds

        revision_count = ctx.get_state("revision_count", default=0) or 0
        prior_revision_instructions = (
            ctx.get_state("last_revision_instructions", default="") or ""
        )
        revision_section = self._build_revision_section(
            revision_count, prior_revision_instructions
        )

        session_id = ctx.get_state("session_id", default=None)

        # ── Pre-flight: fetch image bytes once, detect missing images ─────
        # Doing this upfront avoids double-fetches and produces deterministic
        # synthetic high issues for any image we can't review.
        cover_bytes = self._fetch_image_bytes(draft.cover_image_url, session_id)
        end_bytes = self._fetch_image_bytes(draft.the_end_image_url, session_id)
        page_bytes_by_number: dict[int, bytes | None] = {
            p.page_number: self._fetch_image_bytes(p.image_url, session_id)
            for p in draft.pages
        }

        # ── Build the call descriptors and message payloads ───────────────
        # `descriptors` is the canonical checklist surfaced to the frontend
        # via the `prompt_sent` event so the UI can pre-render every row in
        # `pending` state immediately.
        descriptors: list[dict[str, Any]] = []
        dispatch_specs: list[
            tuple[dict[str, Any], Agent, Message, type, str]
        ] = []  # (descriptor, agent, message, response_format, kind_tag)
        synthetic_issues: list[ReviewIssue] = []
        deferred_failed_events: list[tuple[dict[str, Any], str]] = []

        # Cover ----------------------------------------------------------------
        cover_desc = self._descriptor("cover", "cover", "Cover", page_number=None)
        descriptors.append(cover_desc)
        if cover_bytes:
            dispatch_specs.append((
                cover_desc,
                self._cover_agent,
                self._build_cover_message(
                    draft, cover_bytes, character_descriptions,
                    plot_summary, revision_section,
                ),
                PageReviewResult,
                "page_image",
            ))
        else:
            synthetic_issues.append(self._missing_image_issue("cover", None))
            deferred_failed_events.append((cover_desc, "Cover image was not generated."))

        # Story pages ----------------------------------------------------------
        for page in draft.pages:
            page_desc = self._descriptor(
                f"page-{page.page_number}", "page",
                f"Page {page.page_number}", page_number=page.page_number,
            )
            descriptors.append(page_desc)
            png_bytes = page_bytes_by_number.get(page.page_number)
            if png_bytes:
                dispatch_specs.append((
                    page_desc,
                    self._per_page_agent,
                    self._build_page_message(
                        page, png_bytes, character_descriptions, revision_section,
                    ),
                    PageReviewResult,
                    "page_image",
                ))
            else:
                synthetic_issues.append(
                    self._missing_image_issue("page", page.page_number)
                )
                deferred_failed_events.append((
                    page_desc, f"Page {page.page_number} image was not generated.",
                ))

        # The End --------------------------------------------------------------
        end_desc = self._descriptor("the-end", "the_end", "The End", page_number=None)
        descriptors.append(end_desc)
        if end_bytes:
            dispatch_specs.append((
                end_desc,
                self._the_end_agent,
                self._build_the_end_message(
                    end_bytes, character_descriptions, revision_section,
                ),
                PageReviewResult,
                "page_image",
            ))
        else:
            synthetic_issues.append(self._missing_image_issue("the_end", None))
            deferred_failed_events.append((end_desc, "\"The End\" image was not generated."))

        # Story-text -----------------------------------------------------------
        text_desc = self._descriptor("text", "text", "Story text", page_number=None)
        descriptors.append(text_desc)
        dispatch_specs.append((
            text_desc,
            self._text_agent,
            self._build_text_message(
                draft, character_descriptions, revision_section,
            ),
            StoryTextReviewResult,
            "text",
        ))

        # Cross-page consistency ----------------------------------------------
        # Only worth running when we have enough character images to compare.
        cross_page_inputs: list[tuple[str, bytes]] = []
        if cover_bytes:
            cross_page_inputs.append(("Cover", cover_bytes))
        for page in draft.pages:
            if page.characters_present:
                pb = page_bytes_by_number.get(page.page_number)
                if pb:
                    cross_page_inputs.append((f"Page {page.page_number}", pb))

        if len(cross_page_inputs) >= 2:
            cross_desc = self._descriptor(
                "cross-page", "cross_page", "Cross-page consistency",
                page_number=None,
            )
            descriptors.append(cross_desc)
            dispatch_specs.append((
                cross_desc,
                self._cross_page_agent,
                self._build_cross_page_message(
                    cross_page_inputs, character_descriptions,
                ),
                CrossPageConsistencyResult,
                "cross_page",
            ))

        # ── Emit prompt_sent FIRST so the UI sees the full checklist up front
        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="prompt_sent",
            detail_data={
                "title": draft.title,
                "page_count": len(draft.pages),
                "revision_round": revision_count,
                "total_call_count": len(descriptors),
                "calls": descriptors,
            },
        ))

        # ── Emit deferred missing-image failed events so the UI marks them
        for descriptor, error_msg in deferred_failed_events:
            await ctx.add_event(ProgressDetailEvent(
                executor_id="story_reviewer",
                detail_type="review_call_failed",
                detail_data={**descriptor, "error": error_msg},
            ))

        # ── Dispatch all calls in parallel ───────────────────────────────
        tasks = [
            self._dispatch_call(ctx, desc, agent, message, response_format)
            for (desc, agent, message, response_format, _kind) in dispatch_specs
        ]
        results = await asyncio.gather(*tasks)

        # ── Sort results by type ─────────────────────────────────────────
        # NOTE: per_image_results carries (descriptor, PageReviewResult)
        # pairs so the aggregator can derive each image's slot from the
        # dispatcher's descriptor (call_kind + page_number) rather than
        # trusting the LLM-emitted `location`. Untrusted LLM fields stay
        # out of the routing decision.
        per_image_results: list[tuple[dict[str, Any], PageReviewResult]] = []
        text_result: StoryTextReviewResult | None = None
        cross_page_result: CrossPageConsistencyResult | None = None
        infra_failures: list[str] = []
        for (descriptor, _agent, _message, _rf, kind), (_call_id, value) in zip(
            dispatch_specs, results, strict=True,
        ):
            if isinstance(value, Exception):
                infra_failures.append(
                    f"{descriptor['call_label']}: {type(value).__name__}: {value}"
                )
                continue
            if kind == "page_image":
                per_image_results.append((descriptor, value))
            elif kind == "text":
                text_result = value
            elif kind == "cross_page":
                cross_page_result = value

        # ── Aggregate ────────────────────────────────────────────────────
        # If the text subcall somehow returned None without raising (so it
        # missed the infra_failures list above), classify it as infra here
        # so it routes through the technical-failure branch rather than
        # silently turning into a creative full-regen request.
        if text_result is None and not any(
            f.startswith("Story text") for f in infra_failures
        ):
            infra_failures.append(
                "Story text: subcall produced no result (unexpected None)."
            )

        review = self._aggregate_review(
            per_image_results=per_image_results,
            text_result=text_result,
            cross_page_result=cross_page_result,
            synthetic_issues=synthetic_issues,
            infra_failures=infra_failures,
            page_count=len(draft.pages),
        )

        # Stash this round's instructions so the next review can verify them
        ctx.set_state("last_revision_instructions", review.revision_instructions)

        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="response_received",
            detail_data={
                "approved": review.approved,
                "issue_count": len(review.issues),
                "issues": [
                    {
                        "page": i.page_number,
                        "location": i.location,
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
                    "[StoryReviewer]   Issue (loc=%s page=%s, %s, severity=%s): %s",
                    issue.location,
                    issue.page_number or "—",
                    issue.category,
                    issue.severity,
                    issue.description,
                )

        await ctx.send_message(review)

    # ─── Dispatch wrapper ────────────────────────────────────────────────

    async def _dispatch_call(
        self,
        ctx: WorkflowContext[ReviewResult],
        descriptor: dict[str, Any],
        agent: Agent,
        message: Message,
        response_format: type,
    ) -> tuple[str, Any]:
        """Run one focused review subcall, emitting started/completed/failed
        ProgressDetailEvents and returning ``(call_id, parsed_result | Exception)``.

        Per-subcall ``record_llm_usage`` is called inside the success branch so
        OTEL token telemetry doesn't regress with the fan-out.
        """
        await ctx.add_event(ProgressDetailEvent(
            executor_id="story_reviewer",
            detail_type="review_call_started",
            detail_data=dict(descriptor),
        ))
        try:
            async with self._semaphore:
                result = await agent.run(
                    message,
                    options={
                        "response_format": response_format,
                        # See orchestrator.py — bump max_tokens so reasoning-
                        # model internal tokens don't truncate the issues-list
                        # JSON. Reviewer outputs are small but the
                        # cross-page-consistency call accumulates issues across
                        # 8–10 pages so a generous cap is cheap insurance.
                        "max_tokens": 8000,
                    },
                )
            record_llm_usage(result)
            parsed = result.value
            passed = self._is_call_passed(parsed)
            issues = list(getattr(parsed, "issues", []))
            await ctx.add_event(ProgressDetailEvent(
                executor_id="story_reviewer",
                detail_type="review_call_completed",
                detail_data={
                    **descriptor,
                    "passed": passed,
                    "issue_count": len(issues),
                    "issues": [
                        {
                            "category": i.category,
                            "severity": i.severity,
                            "description": i.description,
                        }
                        for i in issues
                    ],
                },
            ))
            return (descriptor["call_id"], parsed)
        except Exception as e:  # noqa: BLE001 — converted to a failed event
            logger.exception(
                "[StoryReviewer] %s call failed", descriptor["call_label"]
            )
            await ctx.add_event(ProgressDetailEvent(
                executor_id="story_reviewer",
                detail_type="review_call_failed",
                detail_data={**descriptor, "error": str(e)[:200]},
            ))
            return (descriptor["call_id"], e)

    @staticmethod
    def _is_call_passed(parsed: Any) -> bool:
        """Pass/fail summary for the per-call UI chip."""
        if isinstance(parsed, PageReviewResult):
            atxt = parsed.art_text_alignment_pass
            return (
                parsed.character_consistency_pass
                and parsed.age_appropriateness_pass
                and (atxt is None or atxt is True)
            )
        if isinstance(parsed, StoryTextReviewResult):
            return (
                parsed.narrative_coherence_pass
                and parsed.moral_integration_pass
                and parsed.age_appropriateness_pass
            )
        if isinstance(parsed, CrossPageConsistencyResult):
            return parsed.character_consistency_pass
        return True

    # ─── Aggregator ──────────────────────────────────────────────────────

    def _aggregate_review(
        self,
        *,
        per_image_results: list[tuple[dict[str, Any], PageReviewResult]],
        text_result: StoryTextReviewResult | None,
        cross_page_result: CrossPageConsistencyResult | None,
        synthetic_issues: list[ReviewIssue],
        infra_failures: list[str],
        page_count: int,
    ) -> ReviewResult:
        """Merge focused subcall results into the single ReviewResult contract.

        Approval policy MATCHES the legacy single-call reviewer (see legacy
        prompt at ``prompts.py:261-270`` in STORY_REVIEWER_INSTRUCTIONS):
          - any category boolean is False → reject
          - any high-severity issue → reject
          - 4+ medium-severity issues → reject
          - any infrastructure failure → fail closed (technical retry)

        Also stamps the selective-revision routing fields:
          - ``revision_scope`` ∈ {"none", "images_only", "full"}
          - ``image_revision_targets`` — the slot list for ArtDirector when
            ``revision_scope == "images_only"`` (empty otherwise)

        Cross-page DRIFT is enforced via the dedicated CrossPageConsistencyResult,
        not by transitivity through canonical descriptions (which is unsound).

        ``per_image_results`` is a list of ``(descriptor, PageReviewResult)``
        pairs. The descriptor carries the canonical ``call_kind`` and
        ``page_number`` so we can target image revisions by SLOT
        deterministically — never trusting the LLM-emitted ``location``.
        """
        issues: list[ReviewIssue] = list(synthetic_issues)

        # Per-image axes
        art_text_values: list[bool] = []
        char_consist_values: list[bool] = []
        age_appro_values: list[bool] = []
        for _descriptor, r in per_image_results:
            if r.art_text_alignment_pass is not None:
                art_text_values.append(r.art_text_alignment_pass)
            char_consist_values.append(r.character_consistency_pass)
            age_appro_values.append(r.age_appropriateness_pass)
            issues.extend(r.issues)

        # Text-only axes
        if text_result is not None:
            issues.extend(text_result.issues)
            narrative_coherence_pass = text_result.narrative_coherence_pass
            moral_integration_pass = text_result.moral_integration_pass
            age_appro_values.append(text_result.age_appropriateness_pass)
        else:
            # The text call failed (or wasn't dispatched). Fail those axes
            # closed rather than silently passing them.
            narrative_coherence_pass = False
            moral_integration_pass = False

        # Cross-page consistency
        if cross_page_result is not None:
            issues.extend(cross_page_result.issues)
            char_consist_values.append(cross_page_result.character_consistency_pass)
        # If cross-page wasn't dispatched (only 1 character image), don't
        # synthesize a False — there's genuinely nothing to compare.

        art_text_alignment_pass = all(art_text_values) if art_text_values else True
        character_consistency_pass = all(char_consist_values) if char_consist_values else True
        age_appropriateness_pass = all(age_appro_values) if age_appro_values else True

        if infra_failures:
            # Technical failure during review: fail closed and request a full
            # retry. Routes as `full` (existing behaviour) — see the plan's
            # "Out of scope" section for the deferred `review_retry` idea.
            return ReviewResult(
                approved=False,
                issues=[
                    *issues,
                    ReviewIssue(
                        location="whole_story",
                        page_number=None,
                        category="art_text_alignment",
                        severity="high",
                        description=(
                            "Reviewer encountered technical failures and could "
                            "not complete the review: "
                            + "; ".join(infra_failures)
                        ),
                    ),
                ],
                revision_instructions=(
                    "TECHNICAL FAILURE during reviewer subcalls — please "
                    "retry the review. No story changes are required from "
                    "the creative agents.\nDetails:\n- "
                    + "\n- ".join(infra_failures)
                ),
                character_consistency_pass=character_consistency_pass,
                narrative_coherence_pass=narrative_coherence_pass,
                age_appropriateness_pass=age_appropriateness_pass,
                moral_integration_pass=moral_integration_pass,
                art_text_alignment_pass=art_text_alignment_pass,
                revision_scope="full",
                image_revision_targets=[],
            )

        # Count actionable issues (drop "low" severity per legacy policy)
        high_count = sum(1 for i in issues if i.severity == "high")
        medium_count = sum(1 for i in issues if i.severity == "medium")

        all_pass = (
            art_text_alignment_pass
            and character_consistency_pass
            and age_appropriateness_pass
            and narrative_coherence_pass
            and moral_integration_pass
        )
        approved = (
            all_pass
            and high_count < _REJECT_ON_HIGH
            and medium_count < _REJECT_ON_MEDIUM
        )

        revision_instructions = (
            "" if approved else self._synthesize_revision_instructions(issues)
        )

        # ── Selective-revision routing ───────────────────────────────────
        revision_scope: str
        image_revision_targets: list[ImageRevisionTarget] = []
        if approved:
            revision_scope = "none"
        elif self._text_has_issues(text_result) or self._cross_page_has_issues(cross_page_result):
            revision_scope = "full"
        else:
            image_revision_targets = self._build_image_revision_targets(
                per_image_results=per_image_results,
                synthetic_issues=synthetic_issues,
                page_count=page_count,
            )
            # Defensive: if we somehow rejected with no targetable images
            # (e.g. only low-severity issues that tripped a category boolean
            # somewhere unexpected), fall back to a full regen.
            revision_scope = "images_only" if image_revision_targets else "full"

        return ReviewResult(
            approved=approved,
            issues=issues,
            revision_instructions=revision_instructions,
            character_consistency_pass=character_consistency_pass,
            narrative_coherence_pass=narrative_coherence_pass,
            age_appropriateness_pass=age_appropriateness_pass,
            moral_integration_pass=moral_integration_pass,
            art_text_alignment_pass=art_text_alignment_pass,
            revision_scope=revision_scope,
            image_revision_targets=image_revision_targets,
        )

    @staticmethod
    def _text_has_issues(text_result: StoryTextReviewResult | None) -> bool:
        """Whether the story-text subcall flagged anything that requires text revision."""
        if text_result is None:
            return True  # fail closed — text call never produced a result
        if not (
            text_result.narrative_coherence_pass
            and text_result.moral_integration_pass
            and text_result.age_appropriateness_pass
        ):
            return True
        return any(i.severity in ("high", "medium") for i in text_result.issues)

    @staticmethod
    def _cross_page_has_issues(
        cross_page_result: CrossPageConsistencyResult | None,
    ) -> bool:
        """Whether the cross-page subcall flagged character drift across pages."""
        if cross_page_result is None:
            return False  # not dispatched (≤1 char image) is not a failure
        if not cross_page_result.character_consistency_pass:
            return True
        return any(i.severity in ("high", "medium") for i in cross_page_result.issues)

    def _build_image_revision_targets(
        self,
        *,
        per_image_results: list[tuple[dict[str, Any], PageReviewResult]],
        synthetic_issues: list[ReviewIssue],
        page_count: int,
    ) -> list[ImageRevisionTarget]:
        """Group actionable per-image issues into ImageRevisionTargets.

        Targets are keyed by SLOT (0 = cover, 1..N = page N, N+1 = "The End"),
        derived from the dispatcher's descriptor. Two cases produce a target:

          1. The per-image result has at least one high/medium issue.
          2. The per-image result's `_is_call_passed` returned False even
             though the issue list is empty (the LLM tripped a category
             boolean without explaining). A generic fallback note is added
             so ArtDirector still gets actionable instructions.

        Synthetic ``missing image`` issues are folded in as ``is_retry_only``
        targets — ArtDirector reuses the original prompt verbatim for those.
        """
        targets_by_slot: dict[int, dict[str, Any]] = {}

        def _record(slot: int, label: str, notes_lines: list[str], retry_only: bool) -> None:
            entry = targets_by_slot.get(slot)
            if entry is None:
                targets_by_slot[slot] = {
                    "label": label,
                    "notes": list(notes_lines),
                    "is_retry_only": retry_only,
                }
            else:
                entry["notes"].extend(notes_lines)
                # If ANY observation provides real revision notes, the target
                # is no longer retry-only — ArtDirector should refine.
                if not retry_only:
                    entry["is_retry_only"] = False

        for descriptor, result in per_image_results:
            kind = descriptor.get("call_kind")
            page_number = descriptor.get("page_number")
            actionable = [i for i in result.issues if i.severity in ("high", "medium")]
            is_failed = not self._is_call_passed(result)
            if not actionable and not is_failed:
                continue

            if kind == "cover":
                slot, label = 0, "Cover"
            elif kind == "the_end":
                slot, label = page_count + 1, "The End"
            elif kind == "page" and isinstance(page_number, int):
                slot, label = page_number, f"Page {page_number}"
            else:
                # Unrecognized descriptor — shouldn't happen, skip rather
                # than crash. The aggregator's defensive fallback will turn
                # an empty target list into a full regen.
                logger.warning(
                    "[StoryReviewer] Skipping per-image result with unrecognized "
                    "descriptor (kind=%r, page_number=%r).",
                    kind, page_number,
                )
                continue

            notes_lines = [i.description for i in actionable]
            if not notes_lines:
                notes_lines = [
                    "The reviewer flagged a category for this image but did "
                    "not enumerate specific issues. Regenerate this image "
                    "with extra care for character consistency and image-text "
                    "alignment."
                ]
            _record(slot, label, notes_lines, retry_only=False)

        for issue in synthetic_issues:
            if issue.location == "cover":
                slot, label = 0, "Cover"
            elif issue.location == "the_end":
                slot, label = page_count + 1, "The End"
            elif issue.location == "page" and isinstance(issue.page_number, int):
                slot, label = issue.page_number, f"Page {issue.page_number}"
            else:
                continue
            # Missing-image synthetic issues are retry-only — appending their
            # description ("Page 3 image was not generated.") to the prompt
            # would be noise. ArtDirector ignores notes when is_retry_only.
            _record(slot, label, [issue.description], retry_only=True)

        return [
            ImageRevisionTarget(
                slot=slot,
                label=entry["label"],
                revision_notes="\n".join(entry["notes"]),
                is_retry_only=entry["is_retry_only"],
            )
            for slot, entry in sorted(targets_by_slot.items())
        ]

    @staticmethod
    def _synthesize_revision_instructions(issues: list[ReviewIssue]) -> str:
        """Deterministic numbered-list revision instructions, grouped by location.

        Drops "low"-severity items (they are noise per the legacy policy) and
        groups by location: cover → page N (sorted) → the_end → whole_story.
        """
        actionable = [i for i in issues if i.severity in ("high", "medium")]
        if not actionable:
            return ""

        cover_items: list[ReviewIssue] = []
        page_items: dict[int, list[ReviewIssue]] = {}
        end_items: list[ReviewIssue] = []
        whole_items: list[ReviewIssue] = []
        for i in actionable:
            if i.location == "cover":
                cover_items.append(i)
            elif i.location == "the_end":
                end_items.append(i)
            elif i.location == "whole_story":
                whole_items.append(i)
            else:
                # location == "page" (or default)
                key = i.page_number if isinstance(i.page_number, int) else 0
                page_items.setdefault(key, []).append(i)

        lines: list[str] = []
        counter = 1

        def _line(prefix: str, issue: ReviewIssue) -> str:
            return (
                f"{counter}. {prefix}: [{issue.severity}] [{issue.category}] "
                f"{issue.description}"
            )

        for issue in cover_items:
            lines.append(_line("Cover", issue))
            counter += 1
        for page_num in sorted(page_items.keys()):
            label = f"Page {page_num}" if page_num else "Page (unspecified)"
            for issue in page_items[page_num]:
                lines.append(_line(label, issue))
                counter += 1
        for issue in end_items:
            lines.append(_line("The End", issue))
            counter += 1
        for issue in whole_items:
            lines.append(_line("Whole story", issue))
            counter += 1

        return "\n".join(lines)

    # ─── Message builders ────────────────────────────────────────────────

    @staticmethod
    def _build_revision_section(
        revision_count: int, prior_revision_instructions: str
    ) -> str:
        if not (revision_count and prior_revision_instructions):
            return ""
        return (
            f"REVISION ROUND {revision_count}. The previous round issued these "
            "revision instructions:\n"
            f"{prior_revision_instructions}\n"
            "Verify that any items in scope for THIS subcall were addressed."
        )

    def _build_page_message(
        self,
        page: StoryPage,
        png_bytes: bytes,
        character_descriptions: dict[str, str],
        revision_section: str,
    ) -> Message:
        """Per-page message: scoped metadata + canonical roster + ONE image."""
        canonical_names = list(character_descriptions.keys())
        # Filter descriptions to characters present on this page; pass the
        # FULL roster name list separately so unauthorized-character detection
        # still works (rubber-duck issue #4).
        relevant = {
            n: d for n, d in character_descriptions.items()
            if n in page.characters_present
        }

        text_lines = [
            f"PAGE {page.page_number} of the children's story.",
            "",
            f"Page text:\n{page.text}",
            "",
            f"Characters present on this page: "
            f"{', '.join(page.characters_present) or '(none)'}",
            f"Emotional tone: {page.emotional_tone}",
            f"Image prompt that was used: {page.image_prompt}",
            "",
            "Canonical character roster (the ONLY named characters that may "
            "appear in any image as a prominent figure; anonymous background "
            "figures such as crowds or townspeople are fine when called for "
            "by the narrative):",
            ", ".join(canonical_names) if canonical_names else "(none provided)",
        ]
        if relevant:
            text_lines.append("")
            text_lines.append(
                "Canonical descriptions for characters present on this page:"
            )
            for n, d in relevant.items():
                text_lines.append(f"  - {n}: {d}")
        if revision_section:
            text_lines.extend(["", revision_section])
        text_lines.extend(["", "The rendered illustration for this page is attached below."])

        return Message(
            role="user",
            contents=[
                Content.from_text("\n".join(text_lines)),
                Content.from_data(data=png_bytes, media_type="image/png"),
            ],
        )

    def _build_cover_message(
        self,
        draft: StoryDraft,
        png_bytes: bytes,
        character_descriptions: dict[str, str],
        plot_summary: str,
        revision_section: str,
    ) -> Message:
        canonical_names = list(character_descriptions.keys())
        text_lines = [
            f"COVER illustration for the children's story titled: {draft.title!r}",
            "",
            f"Plot summary: {plot_summary or '(not provided)'}",
            "",
            "Canonical character roster (the ONLY named characters that may "
            "appear as prominent figures):",
            ", ".join(canonical_names) if canonical_names else "(none provided)",
        ]
        if character_descriptions:
            text_lines.append("")
            text_lines.append("Canonical character descriptions:")
            for n, d in character_descriptions.items():
                text_lines.append(f"  - {n}: {d}")
        if revision_section:
            text_lines.extend(["", revision_section])
        text_lines.extend(["", "The rendered cover illustration is attached below."])

        return Message(
            role="user",
            contents=[
                Content.from_text("\n".join(text_lines)),
                Content.from_data(data=png_bytes, media_type="image/png"),
            ],
        )

    def _build_the_end_message(
        self,
        png_bytes: bytes,
        character_descriptions: dict[str, str],
        revision_section: str,
    ) -> Message:
        canonical_names = list(character_descriptions.keys())
        text_lines = [
            "Closing \"The End\" illustration for the children's story.",
            "",
            "Canonical character roster (the ONLY named characters that may "
            "appear as prominent figures; the closing image is often purely "
            "decorative and may not contain any characters):",
            ", ".join(canonical_names) if canonical_names else "(none provided)",
        ]
        if character_descriptions:
            text_lines.append("")
            text_lines.append("Canonical character descriptions:")
            for n, d in character_descriptions.items():
                text_lines.append(f"  - {n}: {d}")
        if revision_section:
            text_lines.extend(["", revision_section])
        text_lines.extend([
            "",
            "The rendered closing illustration is attached below. Decorative "
            "\"The End\" calligraphy and ornate frames are NORMAL and EXPECTED.",
        ])

        return Message(
            role="user",
            contents=[
                Content.from_text("\n".join(text_lines)),
                Content.from_data(data=png_bytes, media_type="image/png"),
            ],
        )

    def _build_text_message(
        self,
        draft: StoryDraft,
        character_descriptions: dict[str, str],
        revision_section: str,
    ) -> Message:
        pages_block = "\n\n".join(
            f"--- PAGE {p.page_number} ---\n{p.text}"
            for p in draft.pages
        )
        text_lines = [
            f"Children's story titled: {draft.title!r}",
            "",
            "PAGES (text only):",
            pages_block,
            "",
            f"MORAL SUMMARY (final-page closing): {draft.moral_summary}",
        ]
        if character_descriptions:
            text_lines.append("")
            text_lines.append(
                "Canonical character descriptions (the ONLY named characters "
                "that should appear in the story):"
            )
            for n, d in character_descriptions.items():
                text_lines.append(f"  - {n}: {d}")
        if revision_section:
            text_lines.extend(["", revision_section])

        return Message(
            role="user",
            contents=[Content.from_text("\n".join(text_lines))],
        )

    def _build_cross_page_message(
        self,
        labeled_images: list[tuple[str, bytes]],
        character_descriptions: dict[str, str],
    ) -> Message:
        """Cross-page consistency message: minimal text + EVERY character image."""
        canonical_names = list(character_descriptions.keys())
        text_lines = [
            "Cross-page character consistency check.",
            "",
            "Canonical character descriptions (the only thing that defines "
            "what each character looks like):",
        ]
        if character_descriptions:
            for n, d in character_descriptions.items():
                text_lines.append(f"  - {n}: {d}")
        else:
            text_lines.append("  (none provided)")
        text_lines.extend([
            "",
            f"Attached below are {len(labeled_images)} character images from "
            "the storybook in order. Each image is preceded by its label. "
            "Verify that the same NAMED character is depicted with the same "
            "species, dominant color, and persistent distinguishing features "
            "across pages. Per-page differences in pose, expression, lighting, "
            "or brush style are NOT drift.",
        ])

        contents: list[Content] = [Content.from_text("\n".join(text_lines))]
        for label, png_bytes in labeled_images:
            contents.append(Content.from_text(f"\n[Attached image: {label}]"))
            contents.append(Content.from_data(data=png_bytes, media_type="image/png"))

        return Message(role="user", contents=contents)

    # ─── Image fetch / descriptor helpers ────────────────────────────────

    def _fetch_image_bytes(
        self, image_url: str | None, session_id: str | None
    ) -> bytes | None:
        """Fetch the PNG bytes for a draft image. Returns None on any failure."""
        if not image_url or not session_id:
            return None
        filename = self._filename_from_url(image_url)
        if not filename:
            return None
        try:
            png_bytes = get_backend().get_draft_image_bytes(session_id, filename)
        except Exception:  # noqa: BLE001 — never let image fetch break review
            logger.warning(
                "[StoryReviewer] Could not fetch image bytes for %s", filename
            )
            return None
        return png_bytes or None

    @staticmethod
    def _descriptor(
        call_id: str,
        call_kind: str,
        call_label: str,
        *,
        page_number: int | None,
    ) -> dict[str, Any]:
        return {
            "call_id": call_id,
            "call_kind": call_kind,
            "call_label": call_label,
            "page_number": page_number,
        }

    @staticmethod
    def _missing_image_issue(
        location: str, page_number: int | None
    ) -> ReviewIssue:
        if location == "cover":
            description = "Cover image was not generated — flagging as a high-severity art_text_alignment failure."
        elif location == "the_end":
            description = "\"The End\" image was not generated — flagging as a high-severity art_text_alignment failure."
        else:
            description = (
                f"Page {page_number} image was not generated — flagging "
                "as a high-severity art_text_alignment failure."
            )
        return ReviewIssue(
            location=location,  # type: ignore[arg-type]
            page_number=page_number,
            category="art_text_alignment",
            severity="high",
            description=description,
        )

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
