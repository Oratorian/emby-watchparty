"""
HLS Token Manager
Generates and validates time-limited tokens for HLS stream access
"""

import logging
import secrets
import time
from datetime import UTC, datetime

from backend.src.config import Config


def attach_hls_token(stream_url: str, token: str) -> str:
    """Attach browser HLS token without corrupting queryless opaque URLs."""
    separator = "&" if "?" in stream_url else "?"
    return f"{stream_url}{separator}token={token}"


class HLSTokenManager:
    """Manages HLS stream access tokens"""

    def __init__(self, config: Config, logger: logging.Logger, max_tokens: int = 10_000):
        self._tokens: dict[str, dict] = {}
        self._config = config
        self._logger = logger
        self._max_tokens = max_tokens

    @property
    def active_token_count(self) -> int:
        return len(self._tokens)

    @property
    def enabled(self) -> bool:
        return self._config.ENABLE_HLS_TOKEN_VALIDATION

    def generate(self, party_id: str, sid: str) -> str | None:
        """Generate a new time-limited token for HLS access"""
        if not self.enabled:
            self._logger.debug("HLS token generation skipped - validation disabled")
            return None

        self._cleanup_expired()
        token = secrets.token_urlsafe(32)
        expires = time.time() + self._config.HLS_TOKEN_EXPIRY
        expires_dt = datetime.fromtimestamp(expires, UTC).isoformat()

        self._tokens[token] = {
            "party_id": party_id,
            "sid": sid,
            "expires": expires,
        }
        while len(self._tokens) > self._max_tokens:
            oldest = min(self._tokens, key=lambda value: self._tokens[value]["expires"])
            del self._tokens[oldest]

        self._logger.debug(
            f"Generated HLS token: {token[:16]}... for party={party_id}, sid={sid}, expires={expires_dt}"
        )
        self._logger.debug(f"Total active tokens: {len(self._tokens)}")

        return token

    def validate(self, token: str, party_exists_fn, user_in_party_fn) -> bool:
        """
        Validate an HLS token.

        Args:
            token: Token string to validate
            party_exists_fn: Callable(party_id) -> bool
            user_in_party_fn: Callable(party_id, sid) -> bool
        """
        if not self.enabled:
            return True

        if not token:
            self._logger.debug("Token validation failed: No token provided")
            return False

        if token not in self._tokens:
            self._logger.debug(f"Token validation failed: Token not found: {token[:16]}...")
            self._logger.debug(
                f"Available tokens: {[t[:16] + '...' for t in list(self._tokens.keys())[:5]]}"
            )
            return False

        data = self._tokens[token]

        if time.time() > data["expires"]:
            self._logger.debug("Token validation failed: Token expired")
            del self._tokens[token]
            return False

        party_id = data["party_id"]
        sid = data["sid"]

        if not party_exists_fn(party_id):
            self._logger.debug(f"Token validation failed: Party {party_id} not found")
            return False

        if not user_in_party_fn(party_id, sid):
            self._logger.debug(f"Token validation failed: User sid {sid} not in party {party_id}")
            return False

        self._logger.debug(f"Token validation successful for party {party_id}, user {sid}")
        return True

    def get_or_create(self, party_id: str, sid: str) -> str | None:
        """Get existing valid token for user or generate a new one"""
        for token, data in self._tokens.items():
            if (
                data["party_id"] == party_id
                and data["sid"] == sid
                and time.time() <= data["expires"]
            ):
                self._logger.debug(f"Reusing existing token for party {party_id}, sid {sid}")
                return token

        new_token = self.generate(party_id, sid)
        if new_token:
            self._logger.debug(
                f"Generated new token for party {party_id}, sid {sid}: {new_token[:16]}..."
            )
        return new_token

    def get_party_id(self, token: str) -> str | None:
        """Return the party_id this HLS token was minted for, or None."""
        data = self._tokens.get(token)
        if not data:
            return None
        if time.time() > data["expires"]:
            return None
        return data["party_id"]

    def get_claims(self, token: str) -> tuple[str, str] | None:
        data = self._tokens.get(token)
        if not data or time.time() > data["expires"]:
            return None
        return str(data["party_id"]), str(data["sid"])

    def revoke_party(self, party_id: str) -> int:
        """Wipe every token issued for this party. Returns count removed.

        Called when a party is dissolved (static session disabled, party
        deleted) so leftover tokens can't keep HLS streams alive past
        the party's lifetime.
        """
        victims = [t for t, d in self._tokens.items() if d.get("party_id") == party_id]
        for token in victims:
            del self._tokens[token]
        if victims:
            self._logger.info(f"Revoked {len(victims)} HLS tokens for party {party_id}")
        return len(victims)

    def revoke_user(self, party_id: str, sid: str) -> int:
        """Revoke every token owned by one party participant."""
        victims = [
            token
            for token, data in self._tokens.items()
            if data.get("party_id") == party_id and data.get("sid") == sid
        ]
        for token in victims:
            del self._tokens[token]
        return len(victims)

    def revoke_all(self) -> int:
        """Revoke every process-owned HLS token during shutdown."""
        count = len(self._tokens)
        self._tokens.clear()
        return count

    def _cleanup_expired(self):
        """Remove expired tokens"""
        now = time.time()
        expired = [t for t, d in self._tokens.items() if now > d["expires"]]
        if expired:
            self._logger.debug(f"Cleaning up {len(expired)} expired HLS tokens")
            for token in expired:
                self._logger.debug(
                    f"Removed expired token: {token[:16]}... "
                    f"(party={self._tokens[token]['party_id']}, sid={self._tokens[token]['sid']})"
                )
                del self._tokens[token]
