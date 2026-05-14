"""Azure Blob Storage backend, authenticated via DefaultAzureCredential.

No shared keys, no SAS tokens — RBAC only.  The web app's system-assigned
managed identity needs ``Storage Blob Data Contributor`` on the container.

Layout inside the blob container mirrors the on-disk layout used by
``LocalBackend``:

    {story_id}/meta.json
    {story_id}/story.json
    {story_id}/events.json
    {story_id}/images/<file>
    _drafts/{session_id}/images/<file>

Configuration (env vars):
    AZURE_STORAGE_ACCOUNT_NAME      — e.g. "ststoryprod001"  (required)
    AZURE_STORAGE_CONTAINER_NAME    — defaults to "demo-stories"
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContainerClient

from .base import StorageBackend

logger = logging.getLogger(__name__)

_DRAFTS_PREFIX = "_drafts"


def _is_safe_segment(value: str) -> bool:
    """Reject anything that could escape its intended prefix.

    Blob *names* allow ``/`` (it's how we model folders), but the segments
    we accept from the URL or model fields must not contain it — otherwise
    a request for ``story_id="../something"`` could read another story.
    """
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


class BlobBackend(StorageBackend):
    def __init__(
        self,
        account_name: str | None = None,
        container_name: str | None = None,
    ) -> None:
        account_name = account_name or os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
        if not account_name:
            raise RuntimeError(
                "BlobBackend requires AZURE_STORAGE_ACCOUNT_NAME to be set."
            )
        self._container_name = (
            container_name
            or os.environ.get("AZURE_STORAGE_CONTAINER_NAME")
            or "demo-stories"
        )
        self._service: BlobServiceClient = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        self._container: ContainerClient = self._service.get_container_client(
            self._container_name
        )
        # The container is provisioned by Bicep, but creating it here is
        # cheap, idempotent, and lets local-against-real-azure dev work
        # without a separate provisioning step.
        try:
            self._container.create_container()
            logger.info(
                "[storage:blob] Created container %r", self._container_name
            )
        except Exception:
            # Already exists, or insufficient permission to create — either
            # way, we'll surface real errors on first read/write.
            pass

    # ── Internal helpers ─────────────────────────────────────────────────

    def _story_meta_blob(self, story_id: str) -> str:
        return f"{story_id}/meta.json"

    def _story_story_blob(self, story_id: str) -> str:
        return f"{story_id}/story.json"

    def _story_events_blob(self, story_id: str) -> str:
        return f"{story_id}/events.json"

    def _story_image_blob(self, story_id: str, filename: str) -> str:
        return f"{story_id}/images/{filename}"

    def _draft_image_blob(self, session_id: str, filename: str) -> str:
        return f"{_DRAFTS_PREFIX}/{session_id}/images/{filename}"

    def _read_text(self, blob_name: str) -> str | None:
        try:
            return (
                self._container.get_blob_client(blob_name)
                .download_blob()
                .readall()
                .decode("utf-8")
            )
        except ResourceNotFoundError:
            return None

    def _read_bytes(self, blob_name: str) -> bytes | None:
        try:
            return (
                self._container.get_blob_client(blob_name)
                .download_blob()
                .readall()
            )
        except ResourceNotFoundError:
            return None

    def _write_bytes(
        self,
        blob_name: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"overwrite": True}
        if content_type is not None:
            from azure.storage.blob import ContentSettings

            kwargs["content_settings"] = ContentSettings(content_type=content_type)
        self._container.upload_blob(blob_name, data, **kwargs)

    def _list_top_level_dirs(self) -> Iterable[str]:
        """Yield the first segment of every blob name in the container,
        deduplicated.  Used to enumerate stories.
        """
        seen: set[str] = set()
        for blob in self._container.list_blobs():
            head = blob.name.split("/", 1)[0]
            if head and head not in seen:
                seen.add(head)
                yield head

    # ── Saved demo stories ───────────────────────────────────────────────

    def list_demo_stories(self) -> list[dict[str, Any]]:
        metas: list[dict[str, Any]] = []
        for story_id in self._list_top_level_dirs():
            if story_id.startswith("_") or story_id.startswith("."):
                continue
            text = self._read_text(self._story_meta_blob(story_id))
            if not text:
                continue
            try:
                metas.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        # Sort by title to match LocalBackend's ordering.
        metas.sort(key=lambda m: m.get("title", "").lower())
        return metas

    def get_demo_story(self, story_id: str) -> dict[str, Any] | None:
        if not _is_safe_segment(story_id):
            return None
        meta_text = self._read_text(self._story_meta_blob(story_id))
        story_text = self._read_text(self._story_story_blob(story_id))
        events_text = self._read_text(self._story_events_blob(story_id))
        if meta_text is None or story_text is None or events_text is None:
            return None
        try:
            return {
                "meta": json.loads(meta_text),
                "story": json.loads(story_text),
                "events": json.loads(events_text),
            }
        except json.JSONDecodeError:
            return None

    def get_demo_image_bytes(self, story_id: str, filename: str) -> bytes | None:
        if not _is_safe_segment(story_id) or not _is_safe_segment(filename):
            return None
        return self._read_bytes(self._story_image_blob(story_id, filename))

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
        self._write_bytes(
            self._story_meta_blob(story_id),
            json.dumps(meta, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        self._write_bytes(
            self._story_story_blob(story_id),
            json.dumps(story, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        self._write_bytes(
            self._story_events_blob(story_id),
            json.dumps(events, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def write_demo_image(
        self, story_id: str, filename: str, png_bytes: bytes
    ) -> None:
        if not _is_safe_segment(story_id) or not _is_safe_segment(filename):
            raise ValueError("Invalid story_id or filename")
        self._write_bytes(
            self._story_image_blob(story_id, filename),
            png_bytes,
            content_type=_guess_content_type(filename),
        )

    # ── Drafts ───────────────────────────────────────────────────────────

    def save_draft_image(
        self, session_id: str, filename: str, png_bytes: bytes
    ) -> str:
        if not _is_safe_segment(session_id) or not _is_safe_segment(filename):
            raise ValueError("Invalid session_id or filename")
        self._write_bytes(
            self._draft_image_blob(session_id, filename),
            png_bytes,
            content_type=_guess_content_type(filename),
        )
        return f"/api/drafts/{session_id}/images/{filename}"

    def get_draft_image_bytes(
        self, session_id: str, filename: str
    ) -> bytes | None:
        if not _is_safe_segment(session_id) or not _is_safe_segment(filename):
            return None
        return self._read_bytes(self._draft_image_blob(session_id, filename))

    def promote_draft_to_demo_story(
        self, session_id: str, story_id: str
    ) -> bool:
        if not _is_safe_segment(session_id) or not _is_safe_segment(story_id):
            raise ValueError("Invalid session_id or story_id")
        prefix = f"{_DRAFTS_PREFIX}/{session_id}/images/"
        moved = False
        for blob in self._container.list_blobs(name_starts_with=prefix):
            filename = blob.name.split("/")[-1]
            data = self._read_bytes(blob.name)
            if data is None:
                continue
            self._write_bytes(
                self._story_image_blob(story_id, filename),
                data,
                content_type=_guess_content_type(filename),
            )
            try:
                self._container.delete_blob(blob.name)
            except ResourceNotFoundError:
                pass
            moved = True
        return moved

    def cleanup_old_drafts(self, max_age_seconds: int = 86_400) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        prefix = f"{_DRAFTS_PREFIX}/"
        # Group blobs by session id; delete a session only if *every* blob
        # under it is older than the cutoff (don't half-delete an in-flight
        # generation).
        sessions: dict[str, list[Any]] = {}
        for blob in self._container.list_blobs(name_starts_with=prefix):
            parts = blob.name.split("/", 3)  # ['_drafts', '<sid>', 'images', '<file>']
            if len(parts) < 2:
                continue
            sessions.setdefault(parts[1], []).append(blob)

        removed = 0
        for sid, blobs in sessions.items():
            if any(b.last_modified and b.last_modified > cutoff for b in blobs):
                continue
            for b in blobs:
                try:
                    self._container.delete_blob(b.name)
                except ResourceNotFoundError:
                    pass
            removed += 1
        if removed:
            logger.info(
                "[storage:blob] Cleaned up %d expired draft session(s)", removed
            )
        return removed

    # ── Seeding ──────────────────────────────────────────────────────────

    def seed_if_empty(self, source_dir: Path) -> int:
        if not source_dir.is_dir():
            return 0
        if self.list_demo_stories():
            return 0
        seeded = 0
        for story_dir in source_dir.iterdir():
            if not story_dir.is_dir():
                continue
            if story_dir.name.startswith("_") or story_dir.name.startswith("."):
                continue
            story_id = story_dir.name
            try:
                # Upload every file beneath the story folder, preserving
                # relative paths so .../images/cover.png lands at
                # {story_id}/images/cover.png inside the container.
                for path in story_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(story_dir).as_posix()
                    self._write_bytes(
                        f"{story_id}/{rel}",
                        path.read_bytes(),
                        content_type=_guess_content_type(path.name),
                    )
                seeded += 1
            except Exception as exc:  # noqa: BLE001 — surface but keep going
                logger.warning(
                    "[storage:blob] Failed to seed %s: %s", story_id, exc
                )
        if seeded:
            logger.info("[storage:blob] Seeded %d demo story/stories", seeded)
        return seeded


def _guess_content_type(filename: str) -> str | None:
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".json"):
        return "application/json"
    return None
