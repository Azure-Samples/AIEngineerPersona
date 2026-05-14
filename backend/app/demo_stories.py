"""demo_stories.py — façade over the configurable storage backend.

Public API (used by main.py and the ArtDirector agent):

    list_demo_stories()                        -> list[meta]
    get_demo_story(story_id)                   -> {meta, story, events} | None
    get_demo_image_bytes(story_id, filename)   -> bytes | None
    save_draft_image(session_id, fname, bytes) -> str (API URL)
    get_draft_image_bytes(session_id, fname)   -> bytes | None
    save_demo_story(payload)                   -> story_id
    cleanup_old_drafts(max_age_seconds=...)    -> count
    seed_demo_stories_if_empty()               -> count

The on-disk layout (or its blob-prefix equivalent) is::

    {story_id}/meta.json
    {story_id}/story.json
    {story_id}/events.json
    {story_id}/images/<file>
    _drafts/{session_id}/images/<file>

The actual storage (filesystem vs. Azure Blob) is selected by the
``STORAGE_BACKEND`` environment variable; see :mod:`app.storage`.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

from .storage import get_backend
from .config import settings

logger = logging.getLogger(__name__)


# ─── Public API ──────────────────────────────────────────────────────────────


def list_demo_stories() -> list[dict[str, Any]]:
    return get_backend().list_demo_stories()


def get_demo_story(story_id: str) -> dict[str, Any] | None:
    return get_backend().get_demo_story(story_id)


def get_demo_image_bytes(story_id: str, filename: str) -> bytes | None:
    return get_backend().get_demo_image_bytes(story_id, filename)


def save_draft_image(session_id: str, filename: str, png_bytes: bytes) -> str:
    return get_backend().save_draft_image(session_id, filename, png_bytes)


def get_draft_image_bytes(session_id: str, filename: str) -> bytes | None:
    return get_backend().get_draft_image_bytes(session_id, filename)


def cleanup_old_drafts(max_age_seconds: int = 86_400) -> int:
    return get_backend().cleanup_old_drafts(max_age_seconds)


def seed_demo_stories_if_empty() -> int:
    """Seed the bundled sample stories into the backend if it has none.

    Source defaults to ``backend/demo_stories`` baked into the image, but can
    be overridden via ``SEED_DEMO_STORIES_DIR`` (the cloud Dockerfile sets
    this).
    """
    src = Path(
        os.environ.get(
            "SEED_DEMO_STORIES_DIR",
            str(Path(__file__).parent.parent / "demo_stories"),
        )
    )
    return get_backend().seed_if_empty(src)


def save_demo_story(payload: dict[str, Any]) -> str:
    """Save a story snapshot.

    The payload is shaped as ``{meta, story, events, session_id?}``.

    Two payload flavours are supported:

      1. **URL-based (preferred, current frontend).**  The story's image URLs
         already point at ``/api/drafts/{session_id}/images/...`` because the
         ArtDirector wrote each image during generation.  We promote the
         drafts to ``{story_id}/images/`` and rewrite the URLs in the saved
         JSON to ``/api/demo-stories/{story_id}/images/...`` — no base64
         work, no re-encoding.

      2. **Legacy data-URI (fallback).**  If a URL doesn't match the drafts
         pattern but does start with ``data:image/...;base64,``, we decode
         it and write the bytes ourselves.

    Returns the story_id.
    """
    backend = get_backend()

    meta = payload.get("meta", {})
    story_id = meta.get("id", "")
    if not story_id:
        title = meta.get("title", "untitled")
        story_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        meta["id"] = story_id
    if not story_id or "/" in story_id or "\\" in story_id or ".." in story_id:
        raise ValueError(f"Invalid story_id: {story_id!r}")

    # Stamp the meta with the deployment names of every model that participated
    # in this generation.  Captured server-side from settings so the frontend
    # never has to know (or be trusted with) model identities.  Stored as a
    # plain list of strings; the Saved Stories page renders them as chips.
    seen: set[str] = set()
    models_used: list[str] = []
    for name in (
        settings.foundry_model_deployment_name,
        settings.foundry_image_model_deployment_name,
    ):
        if name and name not in seen:
            seen.add(name)
            models_used.append(name)
    meta["models_used"] = models_used

    session_id = payload.get("session_id") or ""
    story = payload.get("story", {})
    events = payload.get("events", [])

    # Step 1: promote any draft images for this session.  No-op if there
    # are none (e.g. the legacy data-URI path or a re-save).
    if (
        session_id
        and "/" not in session_id
        and "\\" not in session_id
        and ".." not in session_id
    ):
        backend.promote_draft_to_demo_story(session_id, story_id)

    drafts_prefix = f"/api/drafts/{session_id}/images/" if session_id else None
    final_prefix = f"/api/demo-stories/{story_id}/images"

    def _rewrite(url: str | None, fallback_filename: str) -> str | None:
        """Map an image URL into its final, post-save form.

        - ``/api/drafts/{sid}/images/x.png`` -> ``/api/demo-stories/{id}/images/x.png``
        - ``data:image/...;base64,...``      -> write bytes, return final URL
        - anything else                       -> unchanged
        """
        if not url:
            return url
        if drafts_prefix and url.startswith(drafts_prefix):
            return f"{final_prefix}/{url[len(drafts_prefix):]}"
        if url.startswith("data:image"):
            match = re.match(r"data:image/(\w+);base64,(.+)", url, re.DOTALL)
            if not match:
                return url
            ext, b64 = match.group(1), match.group(2)
            fname = f"{fallback_filename}.{ext}"
            backend.write_demo_image(story_id, fname, base64.b64decode(b64))
            return f"{final_prefix}/{fname}"
        return url

    if story.get("cover_image_url"):
        story["cover_image_url"] = _rewrite(story["cover_image_url"], "cover")
        meta["cover_image_url"] = story["cover_image_url"]

    if story.get("the_end_image_url"):
        story["the_end_image_url"] = _rewrite(story["the_end_image_url"], "the_end")

    for page in story.get("pages", []):
        if page.get("image_url"):
            page["image_url"] = _rewrite(
                page["image_url"], f"page_{page['page_number']}"
            )

    for evt in events:
        if evt.get("type") == "detail":
            data = evt.get("data", {})
            if (
                data.get("detail_type") == "image_completed"
                and data.get("data", {}).get("image_url")
            ):
                inner = data["data"]
                label = inner.get("label", "unknown").replace(" ", "_").lower()
                inner["image_url"] = _rewrite(inner["image_url"], f"evt_{label}")

    backend.write_demo_story(story_id, meta=meta, story=story, events=events)
    return story_id
