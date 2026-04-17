"""
demo_stories.py — helpers to enumerate and load pre-captured demo stories.

Each demo story lives in:
  backend/demo_stories/{story_id}/
    meta.json    ← {id, title, description, moral, cover_image_url}
    story.json   ← StoryResponse with image URLs rewritten to /api/demo-stories/{id}/images/{file}
    events.json  ← list of SSE-style progress/detail event dicts
    images/      ← local copies of all images
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Resolve the demo_stories directory relative to this file's location:
# backend/app/demo_stories.py  → backend/demo_stories/
_DEMO_ROOT = Path(__file__).parent.parent / "demo_stories"


def _story_dir(story_id: str) -> Path:
    return _DEMO_ROOT / story_id


def list_demo_stories() -> list[dict[str, Any]]:
    """Return a list of meta dicts for all available demo stories, sorted by title."""
    metas: list[dict[str, Any]] = []
    if not _DEMO_ROOT.is_dir():
        return metas
    for entry in sorted(_DEMO_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            metas.append(meta)
        except (json.JSONDecodeError, OSError):
            continue
    return metas


def get_demo_story(story_id: str) -> dict[str, Any] | None:
    """Return {meta, story, events} for a single demo story, or None if not found."""
    d = _story_dir(story_id)
    if not d.is_dir():
        return None
    try:
        meta   = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        story  = json.loads((d / "story.json").read_text(encoding="utf-8"))
        events = json.loads((d / "events.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return {"meta": meta, "story": story, "events": events}


def get_demo_image_path(story_id: str, filename: str) -> Path | None:
    """Return the absolute Path to a demo story image file, or None if not found.

    The filename is validated to prevent path traversal attacks.
    """
    # Reject any path separators or parent-directory components
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    image_path = _story_dir(story_id) / "images" / filename
    if not image_path.is_file():
        return None
    return image_path


def save_demo_story(payload: dict[str, Any]) -> str:
    """Save a story snapshot as a new demo story.

    Expects payload with: story, events, meta (id, title, description, moral).
    Extracts base64 images from the story and saves them as separate files,
    rewriting image_url fields to point at the /api/demo-stories/{id}/images/ endpoint.

    Returns the story_id.
    """
    import base64
    import re

    meta = payload.get("meta", {})
    story_id = meta.get("id", "")
    if not story_id:
        # Generate an id from the title
        title = meta.get("title", "untitled")
        story_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        meta["id"] = story_id

    story_dir = _story_dir(story_id)
    images_dir = story_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    story = payload.get("story", {})
    image_api_base = f"/api/demo-stories/{story_id}/images"

    def _extract_and_save(data_uri: str | None, filename: str) -> str | None:
        """Save a base64 data URI as a file and return the API URL."""
        if not data_uri or not data_uri.startswith("data:image"):
            return data_uri
        match = re.match(r"data:image/(\w+);base64,(.+)", data_uri, re.DOTALL)
        if not match:
            return data_uri
        ext = match.group(1)
        b64 = match.group(2)
        fname = f"{filename}.{ext}"
        (images_dir / fname).write_bytes(base64.b64decode(b64))
        return f"{image_api_base}/{fname}"

    # Extract cover and end images
    if story.get("cover_image_url"):
        story["cover_image_url"] = _extract_and_save(story["cover_image_url"], "cover")
        meta["cover_image_url"] = story["cover_image_url"]

    if story.get("the_end_image_url"):
        story["the_end_image_url"] = _extract_and_save(story["the_end_image_url"], "the_end")

    # Extract page images
    for page in story.get("pages", []):
        if page.get("image_url"):
            page["image_url"] = _extract_and_save(
                page["image_url"], f"page_{page['page_number']}"
            )

    # Also rewrite image URLs inside events (detail events with image_completed)
    events = payload.get("events", [])
    for evt in events:
        if evt.get("type") == "detail":
            data = evt.get("data", {})
            if data.get("detail_type") == "image_completed" and data.get("data", {}).get("image_url"):
                inner = data["data"]
                label = inner.get("label", "unknown").replace(" ", "_").lower()
                inner["image_url"] = _extract_and_save(inner["image_url"], f"evt_{label}")

    # Write files
    (story_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (story_dir / "story.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
    (story_dir / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    return story_id
