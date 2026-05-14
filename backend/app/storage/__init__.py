"""Pluggable storage backends for saved/in-progress story content.

Two implementations live alongside this package:

  * ``LocalBackend``  — files on the local filesystem.  Used for local dev
                        and as a fallback in cloud when no other backend is
                        configured.
  * ``BlobBackend``   — Azure Blob Storage accessed via DefaultAzureCredential
                        (no shared keys).  Used in cloud deployments.

Selection is driven by the ``STORAGE_BACKEND`` environment variable
(``local`` or ``blob``); see :func:`get_backend`.
"""
from __future__ import annotations

import logging
import os

from .base import StorageBackend

logger = logging.getLogger(__name__)

_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Return the process-wide ``StorageBackend`` instance, creating it lazily.

    The backend kind is decided once per process from the ``STORAGE_BACKEND``
    env var (default: ``local``).  Switching backends requires a restart.
    """
    global _backend
    if _backend is not None:
        return _backend

    kind = (os.environ.get("STORAGE_BACKEND") or "local").lower()
    if kind == "blob":
        from .blob import BlobBackend
        _backend = BlobBackend()
    elif kind == "local":
        from .local import LocalBackend
        _backend = LocalBackend()
    else:
        raise RuntimeError(
            f"Unknown STORAGE_BACKEND={kind!r}; expected 'local' or 'blob'."
        )

    logger.info("[storage] Using backend: %s", _backend.__class__.__name__)
    return _backend


__all__ = ["StorageBackend", "get_backend"]
