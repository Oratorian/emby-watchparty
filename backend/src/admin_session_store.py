"""
Admin Session Store
Server-side holding area for a logged-in admin's Emby credentials.

Why this exists: Starlette's SessionMiddleware SIGNS the session cookie
but does not ENCRYPT it. The payload is `base64(json)` with an
itsdangerous signature appended, so the signature protects integrity
only -- anyone holding the cookie can base64-decode it and read every
value inside, without the secret and without touching the server.

An Emby admin access token is a bearer credential for the entire Emby
server, not just for Watch Party, so it must not live in a container the
client can read. It is kept here instead, and only an opaque handle goes
into the cookie. That handle is useless on its own: it is a lookup key
into this process's memory, not a credential Emby would ever accept.

This mirrors how party["host_access_token"] has always been held in the
in-memory party dict rather than handed to the browser.
"""

import logging
import secrets
import time
from typing import Dict, Optional


# How long a stashed admin login stays usable. Matches the session
# cookie's 14-day max_age so the handle and the cookie carrying it
# expire together rather than one outliving the other.
ADMIN_SESSION_TTL = 14 * 24 * 60 * 60


class AdminSessionStore:
    """Maps an opaque handle to a set of admin Emby credentials."""

    def __init__(self, logger: logging.Logger, ttl: int = ADMIN_SESSION_TTL):
        self._sessions: Dict[str, dict] = {}
        self._logger = logger
        self._ttl = ttl

    def create(self, access_token: str, user_id: str, username: str,
               is_admin: bool = True) -> str:
        """Stash credentials and return the handle to put in the cookie."""
        handle = secrets.token_urlsafe(32)
        self._sessions[handle] = {
            'access_token': access_token,
            'user_id': user_id,
            'username': username,
            'is_admin': is_admin,
            'expires': time.time() + self._ttl,
        }
        self._logger.debug(
            f"Stored admin session for '{username}' (handle {handle[:8]}...); "
            f"{len(self._sessions)} active"
        )
        self._cleanup_expired()
        return handle

    def get(self, handle: Optional[str]) -> Optional[dict]:
        """Return the stashed credentials, or None if unknown or expired."""
        if not handle:
            return None
        data = self._sessions.get(handle)
        if not data:
            return None
        if time.time() > data['expires']:
            self._logger.debug(f"Admin session expired (handle {handle[:8]}...)")
            del self._sessions[handle]
            return None
        return data

    def revoke(self, handle: Optional[str]) -> None:
        """Drop a stashed session, on logout or failed revalidation."""
        if handle and self._sessions.pop(handle, None):
            self._logger.debug(f"Revoked admin session (handle {handle[:8]}...)")

    def _cleanup_expired(self) -> None:
        now = time.time()
        stale = [h for h, d in self._sessions.items() if now > d['expires']]
        for handle in stale:
            del self._sessions[handle]
        if stale:
            self._logger.debug(f"Cleaned up {len(stale)} expired admin session(s)")
