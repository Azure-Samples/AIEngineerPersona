"""Abstract storage backend interface.

Both the local-filesystem and Azure-Blob implementations honour this contract,
so the rest of the app (``demo_stories.py`` façade, FastAPI endpoints, the
ArtDirector agent) can be written backend-agnostically.

The data model is identical across backends:

  saved demo story:
    {story_id}/meta.json
    {story_id}/story.json
    {story_id}/events.json
    {story_id}/images/<file>

  draft (in-progress generation):
    _drafts/{session_id}/images/<file>
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StorageBackend(ABC):
    # ── Saved demo stories ────────────────────────────────────────────────

    @abstractmethod
    def list_demo_stories(self) -> list[dict[str, Any]]:
        """Return meta dicts for every saved demo story, sorted by title."""

    @abstractmethod
    def get_demo_story(self, story_id: str) -> dict[str, Any] | None:
        """Return ``{meta, story, events}`` for one story, or ``None``."""

    @abstractmethod
    def get_demo_image_bytes(self, story_id: str, filename: str) -> bytes | None:
        """Return raw bytes for a saved-story image, or ``None`` if missing."""

    @abstractmethod
    def write_demo_story(
        self,
        story_id: str,
        *,
        meta: dict[str, Any],
        story: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        """Persist meta/story/events JSON for a saved demo story."""

    @abstractmethod
    def write_demo_image(self, story_id: str, filename: str, png_bytes: bytes) -> None:
        """Persist an image into a saved demo story (used by the legacy
        data-URI fallback path in ``save_demo_story``)."""

    # ── Drafts (in-progress) ──────────────────────────────────────────────

    @abstractmethod
    def save_draft_image(
        self, session_id: str, filename: str, png_bytes: bytes
    ) -> str:
        """Persist a freshly-generated image and return the API URL the
        frontend should request to display it."""

    @abstractmethod
    def get_draft_image_bytes(
        self, session_id: str, filename: str
    ) -> bytes | None:
        """Return raw bytes for an in-progress draft image, or ``None``."""

    @abstractmethod
    def promote_draft_to_demo_story(self, session_id: str, story_id: str) -> bool:
        """Move every image under ``_drafts/{session_id}/images/`` into the
        final ``{story_id}/images/`` location.  Returns ``True`` if any file
        was moved.  Idempotent: re-promoting an already-promoted session is
        a no-op that returns ``False``.
        """

    @abstractmethod
    def cleanup_old_drafts(self, max_age_seconds: int = 86_400) -> int:
        """Remove draft folders/blobs older than ``max_age_seconds`` and
        return the count of *sessions* removed."""

    # ── Setup / housekeeping ──────────────────────────────────────────────

    @abstractmethod
    def seed_if_empty(self, source_dir: Path) -> int:
        """If no saved demo stories exist, copy them in from ``source_dir``
        (a local-filesystem path containing one folder per story).  Returns
        the count of stories seeded.  Safe to call on every start — does
        nothing once anything is in place.
        """
