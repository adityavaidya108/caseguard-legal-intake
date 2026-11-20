from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from backend.app.config import get_settings


class VaultStore:
    """In-memory token vault. Entries expire after VAULT_TTL_MINUTES."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[dict[str, Any], float]] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            review_id
            for review_id, (_, expires_at) in self._entries.items()
            if expires_at <= now
        ]
        for review_id in expired:
            del self._entries[review_id]

    def save(self, vault: dict[str, Any]) -> str:
        ttl_seconds = get_settings().vault_ttl_minutes * 60
        review_id = str(uuid.uuid4())
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            self._purge_expired()
            self._entries[review_id] = (dict(vault), expires_at)
        return review_id

    def get(self, review_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_expired()
            entry = self._entries.get(review_id)
            if entry is None:
                return None
            vault, _expires_at = entry
            return dict(vault)

    def delete(self, review_id: str) -> None:
        with self._lock:
            self._purge_expired()
            self._entries.pop(review_id, None)


vault_store = VaultStore()


def save(vault: dict[str, Any]) -> str:
    return vault_store.save(vault)


def get(review_id: str) -> dict[str, Any] | None:
    return vault_store.get(review_id)


def delete(review_id: str) -> None:
    vault_store.delete(review_id)
