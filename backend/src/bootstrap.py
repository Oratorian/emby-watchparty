"""Secure validation and persistence for restart-required bootstrap settings."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from backend.src.config import BOOTSTRAP_CONFIG_NAME, Config

if TYPE_CHECKING:
    from collections.abc import Callable

BOOTSTRAP_FIELDS = (
    "APP_ENV",
    "EMBY_SERVER_URL",
    "EMBY_API_KEY",
    "SESSION_SECRET",
    "SESSION_COOKIE_SECURE",
    "CORS_ALLOWED_ORIGINS",
    "TRUSTED_PROXY_CIDRS",
    "APP_PREFIX",
    "ENABLE_HLS_TOKEN_VALIDATION",
)
_BOOLEAN_FIELDS = {"SESSION_COOKIE_SECURE", "ENABLE_HLS_TOKEN_VALIDATION"}
_LIST_FIELDS = {"CORS_ALLOWED_ORIGINS", "TRUSTED_PROXY_CIDRS"}


@dataclass
class _AttemptWindow:
    started_at: float
    count: int = 0


@dataclass(frozen=True)
class SetupAttemptDecision:
    allowed: bool
    retry_after: int = 0


class SetupAttemptLimiter:
    """Fixed-window failed-token limiter with per-peer and process-wide caps."""

    def __init__(
        self,
        *,
        peer_limit: int = 5,
        global_limit: int = 100,
        window_seconds: int = 15 * 60,
        max_peers: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._peer_limit = peer_limit
        self._global_limit = global_limit
        self._window_seconds = window_seconds
        self._max_peers = max_peers
        self._clock = clock
        self._peer_windows: dict[str, _AttemptWindow] = {}
        self._global_window: _AttemptWindow | None = None
        self._lock = threading.Lock()

    def record_failure(self, peer: str) -> SetupAttemptDecision:
        now = self._clock()
        with self._lock:
            self._expire_peers(now)
            if self._global_window is None or self._expired(self._global_window, now):
                self._global_window = _AttemptWindow(now)
            peer_window = self._peer_windows.get(peer)
            if peer_window is None:
                self._evict_peer_if_full()
                peer_window = _AttemptWindow(now)
                self._peer_windows[peer] = peer_window

            peer_allowed = peer_window.count < self._peer_limit
            global_allowed = self._global_window.count < self._global_limit
            if peer_allowed:
                peer_window.count += 1
            if global_allowed:
                self._global_window.count += 1
            if peer_allowed and global_allowed:
                return SetupAttemptDecision(True)
            retry_after = max(
                self._retry_after(peer_window, now) if not peer_allowed else 0,
                self._retry_after(self._global_window, now) if not global_allowed else 0,
            )
            return SetupAttemptDecision(False, retry_after)

    def _expired(self, window: _AttemptWindow, now: float) -> bool:
        return now >= window.started_at + self._window_seconds

    def _retry_after(self, window: _AttemptWindow, now: float) -> int:
        return max(1, int(window.started_at + self._window_seconds - now + 0.999))

    def _expire_peers(self, now: float) -> None:
        expired = [
            peer for peer, window in self._peer_windows.items() if self._expired(window, now)
        ]
        for peer in expired:
            self._peer_windows.pop(peer, None)

    def _evict_peer_if_full(self) -> None:
        if len(self._peer_windows) >= self._max_peers:
            oldest = min(self._peer_windows, key=lambda peer: self._peer_windows[peer].started_at)
            self._peer_windows.pop(oldest, None)


def validate_bootstrap_submission(
    current: Config,
    payload: object,
) -> tuple[dict[str, object], dict[str, str]]:
    """Return normalized values plus safe errors for one complete submission."""
    if not isinstance(payload, dict):
        return {}, {"FORM": "Request body must be a JSON object"}

    current_values = current.boot_values()
    normalized: dict[str, object] = {}
    shape_errors: dict[str, str] = {}
    for name in BOOTSTRAP_FIELDS:
        raw = payload.get(name, current_values[name])
        if name in current.explicit_env_fields:
            normalized[name] = current_values[name]
            continue
        if name in _BOOLEAN_FIELDS:
            if not isinstance(raw, bool):
                shape_errors[name] = "Must be true or false"
                normalized[name] = current_values[name]
            else:
                normalized[name] = raw
        elif name in _LIST_FIELDS:
            if isinstance(raw, str):
                normalized[name] = tuple(item.strip() for item in raw.split(",") if item.strip())
            elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
                normalized[name] = tuple(item.strip() for item in raw if item.strip())
            else:
                shape_errors[name] = "Must be a list or comma-separated string"
                normalized[name] = current_values[name]
        elif isinstance(raw, str):
            # Empty secret fields preserve an already configured secret without exposing it.
            if name in {"EMBY_API_KEY", "SESSION_SECRET"} and not raw and current_values[name]:
                normalized[name] = current_values[name]
            else:
                normalized[name] = raw.strip()
        else:
            shape_errors[name] = "Must be text"
            normalized[name] = current_values[name]

    candidate = current.with_boot_values(normalized)
    errors = candidate.startup_errors()
    errors.update(shape_errors)
    for name in current.explicit_env_fields:
        if name in errors:
            errors[name] = "Invalid environment override; change or remove it and restart"
    return normalized, errors


def save_bootstrap_config(project_root: Path, values: dict[str, object]) -> Path:
    """Atomically save bootstrap values beside other mounted persistent data."""
    data_dir = project_root / "data"
    path = data_dir / BOOTSTRAP_CONFIG_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        data_dir.chmod(0o700)

    persisted = {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in values.items()
        if name in BOOTSTRAP_FIELDS
    }
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=data_dir,
            prefix=f"{BOOTSTRAP_CONFIG_NAME}.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as temporary:
            temp_name = temporary.name
            with contextlib.suppress(OSError):
                Path(temp_name).chmod(0o600)
            json.dump(persisted, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            with contextlib.suppress(OSError):
                os.fsync(temporary.fileno())
        Path(temp_name).replace(path)
        temp_name = None
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return path
    finally:
        if temp_name is not None:
            with contextlib.suppress(OSError):
                Path(temp_name).unlink()
