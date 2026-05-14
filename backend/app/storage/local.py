"""Local-filesystem storage backend.

Used for local development (``DEMO_STORIES_DIR`` defaults to
``backend/demo_stories``) and as a fallback in environments without an
Azure Storage account.  Mirrors what previous versions of
``demo_stories.py`` did directly with ``pathlib``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .base import StorageBackend

logger = logging.getLogger(__name__)

_DRAFTS_DIRNAME = "_drafts"


def _is_safe_segment(value: str) -> bool:
    """Reject anything that could escape the intended directory."""
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


class LocalBackend(StorageBackend):
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(
            root
            if root is not None
            else os.environ.get(
                "DEMO_STORIES_DIR",
                str(Path(__file__).parent.parent.parent / "demo_stories"),
            )
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _story_dir(self, story_id: str) -> Path:
        return self._root / story_id

    def _draft_dir(self, session_id: str) -> Path:
        return self._root / _DRAFTS_DIRNAME / session_id

    # ── Saved demo stories ───────────────────────────────────────────────

    def list_demo_stories(self) -> list[dict[str, Any]]:
        metas: list[dict[str, Any]] = []
        if not self._root.is_dir():
            return metas
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            # Skip drafts sentinel and any hidden/internal entries.
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            meta_path = entry / "meta.json"
            if not meta_path.exists():
                continue
            try:
                metas.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return metas

    def get_demo_story(self, story_id: str) -> dict[str, Any] | None:
        if not _is_safe_segment(story_id):
            return None
        d = self._story_dir(story_id)
        if not d.is_dir():
            return None
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            story = json.loads((d / "story.json").read_text(encoding="utf-8"))
            events = json.loads((d / "events.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return {"meta": meta, "story": story, "events": events}

    def get_demo_image_bytes(self, story_id: str, filename: str) -> bytes | None:
        if not _is_safe_segment(story_id) or not _is_safe_segment(filename):
            return None
        path = self._story_dir(story_id) / "images" / filename
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def write_demo_story(
        self,
        story_id: str,
        *,
        meta: dict[str, Any],
        story: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        if not _is_safe_segment(story_id):
            raise ValueError(f"Invalid story_id: {story_id!r}")
        d = self._story_dir(story_id)
        (d / "images").mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (d / "story.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
        (d / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    def write_demo_image(self, story_id: str, filename: str, png_bytes: bytes) -> None:
        if not _is_safe_segment(story_id) or not _is_safe_segment(filename):
            raise ValueError("Invalid story_id or filename")
        images_dir = self._story_dir(story_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / filename).write_bytes(png_bytes)

    # ── Drafts ───────────────────────────────────────────────────────────

    def save_draft_image(
        self, session_id: str, filename: str, png_bytes: bytes
    ) -> str:
        if not _is_safe_segment(session_id) or not _is_safe_segment(filename):
            raise ValueError("Invalid session_id or filename")
        images_dir = self._draft_dir(session_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / filename).write_bytes(png_bytes)
        return f"/api/drafts/{session_id}/images/{filename}"

    def get_draft_image_bytes(
        self, session_id: str, filename: str
    ) -> bytes | None:
        if not _is_safe_segment(session_id) or not _is_safe_segment(filename):
            return None
        path = self._draft_dir(session_id) / "images" / filename
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def promote_draft_to_demo_story(
        self, session_id: str, story_id: str
    ) -> bool:
        if not _is_safe_segment(session_id) or not _is_safe_segment(story_id):
            raise ValueError("Invalid session_id or story_id")
        src_images = self._draft_dir(session_id) / "images"
        if not src_images.is_dir():
            return False
        dest_images = self._story_dir(story_id) / "images"
        dest_images.mkdir(parents=True, exist_ok=True)
        moved = False
        for item in src_images.iterdir():
            if not item.is_file():
                continue
            target = dest_images / item.name
            try:
                shutil.move(str(item), str(target))
            except OSError:
                # Cross-device or other rename failure — copy and unlink.
                shutil.copy2(item, target)
                try:
                    item.unlink()
                except OSError:
                    pass
            moved = True
        # Clean up the now-empty draft tree.
        shutil.rmtree(self._draft_dir(session_id), ignore_errors=True)
        return moved

    def cleanup_old_drafts(self, max_age_seconds: int = 86_400) -> int:
        drafts_root = self._root / _DRAFTS_DIRNAME
        if not drafts_root.is_dir():
            return 0
        cutoff = time.time() - max_age_seconds
        removed = 0
        for entry in drafts_root.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.info(
                "[storage:local] Cleaned up %d expired draft folder(s)", removed
            )
        return removed

    # ── Seeding ──────────────────────────────────────────────────────────

    def seed_if_empty(self, source_dir: Path) -> int:
        """If no saved stories exist under ``self._root``, copy them in
        from the bundled ``source_dir``.

        Used in cloud where the persistent volume / blob container starts
        empty on first deploy.
        """
        if not source_dir.is_dir():
            return 0
        # If anything story-shaped is already here, do nothing.
        if self.list_demo_stories():
            return 0
        seeded = 0
        for entry in source_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            target = self._root / entry.name
            try:
                shutil.copytree(entry, target, dirs_exist_ok=True)
                seeded += 1
            except OSError as exc:
                logger.warning(
                    "[storage:local] Failed to seed %s: %s", entry.name, exc
                )
        if seeded:
            logger.info("[storage:local] Seeded %d demo story/stories", seeded)
        return seeded
