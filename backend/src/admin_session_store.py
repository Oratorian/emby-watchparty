"""Server-side storage for standalone administrator sessions.

Starlette's session cookie is signed, not encrypted.  Only an opaque
handle belongs in that cookie; Emby credentials stay in this process.
"""

from dataclasses import dataclass
import secrets
import threading
import time
from typing import Optional


@dataclass(frozen=True)
class AdminSession:
    username: str
    access_token: str
    user_id: str
    is_admin: bool
    expires_at: float


class AdminSessionStore:
    """Bounded, in-memory TTL store for standalone admin credentials."""

    def __init__(self, ttl_seconds: int = 24 * 60 * 60, max_entries: int = 1024):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, AdminSession] = {}
        self._lock = threading.Lock()

    def create(self, username: str, access_token: str, user_id: str,
               is_admin: bool = True) -> str:
        now = time.monotonic()
        handle = secrets.token_urlsafe(32)
        session = AdminSession(
            username=username,
            access_token=access_token,
            user_id=user_id,
            is_admin=is_admin,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._prune_locked(now)
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda key: self._entries[key].expires_at)
                self._entries.pop(oldest, None)
            self._entries[handle] = session
        return handle

    def get(self, handle: Optional[str]) -> Optional[AdminSession]:
        if not handle:
            return None
        now = time.monotonic()
        with self._lock:
            session = self._entries.get(handle)
            if not session:
                return None
            if session.expires_at <= now:
                self._entries.pop(handle, None)
                return None
            return session

    def revoke(self, handle: Optional[str]) -> None:
        if not handle:
            return
        with self._lock:
            self._entries.pop(handle, None)

    def clear(self) -> int:
        """Revoke every process-owned administrator session."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, value in self._entries.items() if value.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
