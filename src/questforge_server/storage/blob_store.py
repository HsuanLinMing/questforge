# src/questforge_server/storage/blob_store.py
"""
Abstract BlobStore interface.

Implementations:
  - BlobStoreR2   (Cloudflare R2 via S3-compatible API)
  - BlobStoreNoop (writes nothing; used when R2 is not configured)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BlobStore(ABC):
    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "audio/wav") -> str:
        """Upload *data* at *key*.  Returns the public URL."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if the object exists (best-effort; may call HEAD)."""


class BlobStoreNoop(BlobStore):
    """Falls back to no-op when R2/S3 credentials are absent."""

    def put_bytes(self, key: str, data: bytes, content_type: str = "audio/wav") -> str:
        # No-op: caller must serve files from local disk instead.
        return ""

    def exists(self, key: str) -> bool:
        return False
