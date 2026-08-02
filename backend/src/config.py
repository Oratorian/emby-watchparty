"""
Configuration for Emby Watch Party application

Two tiers:
- EnvConfig: frozen, loaded from .env at boot (restart required to change)
- RuntimeConfig: mutable, loaded from config.json (hot-reloadable via admin panel)
- Config: facade combining both, backward compatible with config.X access
"""

import json
import os
import threading
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import get_origin
from urllib.parse import urlsplit

from dotenv import load_dotenv

from backend.src.quality import DEFAULT_ENABLED_OPTIONS, QUALITY_TIERS, RESOLUTION_ORDER


def _bool(value: str) -> bool:
    """Convert env string to bool"""
    return value.lower() in ('true', '1', 'yes')


CONFIG_JSON_PATH = Path(__file__).parent.parent.parent / 'config.json'


@dataclass(frozen=True)
class EnvConfig:
    """Boot-essential settings from .env (restart required)"""

    WATCH_PARTY_BIND: str
    WATCH_PARTY_PORT: int
    APP_PREFIX: str
    SESSION_EXPIRY: int
    EMBY_SERVER_URL: str
    EMBY_API_KEY: str
    APP_ENV: str
    SESSION_SECRET: str
    SESSION_COOKIE_SECURE: bool
    CORS_ALLOWED_ORIGINS: tuple[str, ...]
    TRUSTED_PROXY_CIDRS: tuple[str, ...]

    @classmethod
    def from_env(cls) -> 'EnvConfig':
        env_path = Path(__file__).parent.parent.parent / '.env'
        load_dotenv(env_path)

        origins_raw = os.getenv('CORS_ALLOWED_ORIGINS', '*').strip()
        proxy_cidrs_raw = os.getenv('TRUSTED_PROXY_CIDRS', '').strip()
        return cls(
            WATCH_PARTY_BIND=os.getenv('WATCH_PARTY_BIND', '0.0.0.0'),
            WATCH_PARTY_PORT=int(os.getenv('WATCH_PARTY_PORT', '5000')),
            APP_PREFIX=os.getenv('APP_PREFIX', '').rstrip('/'),
            SESSION_EXPIRY=int(os.getenv('SESSION_EXPIRY', '86400')),
            EMBY_SERVER_URL=os.getenv('EMBY_SERVER_URL', 'http://localhost:8096'),
            EMBY_API_KEY=os.getenv('EMBY_API_KEY', ''),
            APP_ENV=os.getenv('APP_ENV', 'development').strip().lower(),
            SESSION_SECRET=os.getenv('SESSION_SECRET', '').strip(),
            SESSION_COOKIE_SECURE=_bool(os.getenv('SESSION_COOKIE_SECURE', 'false')),
            CORS_ALLOWED_ORIGINS=tuple(
                value.strip() for value in origins_raw.split(',') if value.strip()
            ),
            TRUSTED_PROXY_CIDRS=tuple(
                value.strip() for value in proxy_cidrs_raw.split(',') if value.strip()
            ),
        )


@dataclass
class RuntimeConfig:
    """Runtime settings from config.json (hot-reloadable)"""

    # Auth gating.
    # True: party creation requires Emby credentials (creator becomes host).
    # False: anyone can create a party; any member can later log in to host.
    REQUIRE_LOGIN: bool = False

    # Make binge-watching (auto-advance to next episode when current ends)
    # available to hosts. Two-tier toggle: this flag gates whether the
    # control-strip button appears at all; flipping it on does NOT enable
    # auto-advance for any party that's already running -- the host still
    # has to click the button. When the admin flips this OFF mid-session
    # the server emits binge_watch_state_changed with available=False so
    # the button disappears and any pending auto-advance is cancelled.
    BINGE_WATCH_ENABLED: bool = False

    # Countdown shown to the room before auto-advance fires. Any user can
    # hit Cancel during this window; selector wins, but any cancel stops
    # it (so a child grabbing the remote can stop the next episode just
    # by clicking). 4 seconds matches what 1.x used and feels right for
    # "noticed it / decided not to" without feeling laggy.
    BINGE_WATCH_COUNTDOWN_SECONDS: int = 4

    # Force every HLS request to disable Emby's stream-copy fallback.
    # When False (default), Emby decides per-source: h264 within the
    # bitrate cap gets stream-copied (CPU/GPU friendly, segments follow
    # source keyframe spacing). When True, the URL carries
    # `EnableAutoStreamCopy=false` so Emby always re-encodes, producing
    # uniform 6-second segments. Re-enable this if large seeks (Skip
    # Intro, dragging the progress bar a long distance) cause the
    # player to restart from the beginning -- stream-copied segments
    # can be 10+ seconds apart at the source's original keyframe
    # boundaries, which HLS.js can't seek into cleanly.
    FORCE_TRANSCODE: bool = False

    # Quality
    # Which resolution tiers AND which bitrates within each tier the
    # per-user quality dropdown should expose. Shape:
    #     {"1080p": [60000, 50000, ...], "720p": [...], "360p": [], ...}
    # Presence of a key enables the resolution. The value is the subset
    # of bitrates (kbps) the admin wants exposed, intersected at render
    # time with the canonical tier list in backend/src/quality.py. For
    # the resolution-only tiers (360p / 240p / 144p) the value list is
    # ignored -- they always render as a single entry when enabled.
    # `Auto` is always added on top unless FORCE_TRANSCODE is on.
    ENABLED_QUALITY_OPTIONS: dict = field(
        default_factory=lambda: {res: list(kbps) for res, kbps in DEFAULT_ENABLED_OPTIONS.items()}
    )

    # Logging
    LOG_LEVEL: str = 'INFO'
    LOG_TO_FILE: bool = True
    LOG_FILE: str = 'logs/emby-watchparty.log'
    LOG_FORMAT: str = 'rsyslog'
    LOG_MAX_SIZE: int = 10
    CONSOLE_LOG_LEVEL: str = 'WARNING'

    # Security
    MAX_USERS_PER_PARTY: int = 0
    ENABLE_HLS_TOKEN_VALIDATION: bool = True
    HLS_TOKEN_EXPIRY: int = 86400
    ENABLE_RATE_LIMITING: bool = True
    RATE_LIMIT_PARTY_CREATION: str = '5 per hour'
    RATE_LIMIT_API_CALLS: str = '1000 per minute'
    RATE_LIMIT_LOGIN: str = '10 per 15 minutes'
    RATE_LIMIT_AVATAR_RECOVERY: str = '10 per hour'
    RATE_LIMIT_CHAT: str = '5 per 3 seconds'
    RATE_LIMIT_SOCKET_CONNECTIONS: str = '30 per minute'

    # Session
    STATIC_SESSION_ENABLED: bool = False
    STATIC_SESSION_ID: str = 'PARTY'

    # Late joiner vote
    LATE_JOIN_VOTE_ENABLED: bool = True
    LATE_JOIN_VOTE_TIMEOUT_SECONDS: int = 20
    # Cooldown after a failed/cancelled vote before a new late join is
    # allowed. Prevents a malicious user from spamming the party URL to
    # repeatedly pop vote modals on existing watchers.
    LATE_JOIN_VOTE_COOLDOWN_SECONDS: int = 30

    @classmethod
    def from_file(cls, path: Path = CONFIG_JSON_PATH) -> 'RuntimeConfig':
        """Load from config.json, falling back to defaults for missing fields.

        If config.json is corrupted (truncated / not valid JSON) we still
        return defaults, but we side-move the bad file to
        `<path>.corrupt-<timestamp>` and log at warning level so the
        operator has both a signal AND a recoverable copy. Previously
        this was a silent `pass` -- the next admin save would then
        overwrite config.json with defaults, permanently losing every
        prior admin tuning.
        """
        import time as _t
        import shutil
        import logging as _logging
        instance = cls()
        if path.exists():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                instance.update_from_dict(data)
            except json.JSONDecodeError as e:
                backup_path = path.with_name(
                    f"{path.name}.corrupt-{int(_t.time())}"
                )
                backup: Path | None = backup_path
                try:
                    shutil.copy2(path, backup_path)
                except OSError:
                    backup = None
                _logging.getLogger("emby-watchparty").warning(
                    f"config.json is corrupted ({e}); reverted to defaults. "
                    f"Backup at {backup} for recovery."
                )
            except OSError as e:
                _logging.getLogger("emby-watchparty").warning(
                    f"config.json could not be read ({e}); using defaults."
                )
        return instance

    def save(self, path: Path = CONFIG_JSON_PATH):
        """Persist current runtime settings atomically.

        Write to a sibling temp file and os.replace() onto the target.
        Prevents the crash-mid-write case where truncating config.json
        via `open(path, 'w')` and then dying (OOM, power-loss, exception
        during json.dump) leaves a partial or empty file, which
        from_file() then silently swallowed as "use defaults", erasing
        every admin-tuned setting.
        """
        import os
        import tempfile
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory so os.replace() is atomic (rename across
        # filesystems can partial-succeed). NamedTemporaryFile with
        # delete=False so we control the final rename ourselves.
        with tempfile.NamedTemporaryFile(
            mode='w', dir=path.parent, prefix=path.name + '.',
            suffix='.tmp', delete=False, encoding='utf-8',
        ) as tmp:
            json.dump(self.to_dict(), tmp, indent=2)
            tmp.flush()
            try:
                os.fsync(tmp.fileno())
            except OSError:
                pass
            tmp_name = tmp.name
        os.replace(tmp_name, path)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def update_from_dict(self, data: dict) -> tuple[list, list]:
        """Apply validated changes.

        Returns `(changed, rejected)`:
        - changed: field names whose value was updated.
        - rejected: list of `{key, reason}` dicts describing values that
          were dropped because they had the wrong shape or failed
          coercion. Previously these were silently `continue`d and the
          admin UI still rendered "Saved" -- so an invalid HLS_TOKEN_EXPIRY
          or a null LOG_MAX_SIZE left the server on the old value with
          no user-visible signal. The admin router surfaces the reject
          list in the response so the UI can show "Saved (but X was
          not applied: <reason>)".
        """
        changed = []
        rejected: list[dict] = []
        valid_fields = {f.name: f for f in fields(self)}

        # Response-only wrapper keys the admin GET /config endpoint
        # returns alongside the real fields (schemas.py:RuntimeConfigResponse
        # ships `error: Optional[str]` as a status slot). The frontend
        # re-submits its whole config object on Save, so these leak into
        # the payload every time. Silently drop them instead of listing
        # them in `rejected` where they'd show up as a scary "Not
        # applied: error (unknown field)" line after a plain no-op Save.
        _RESPONSE_WRAPPER_KEYS = {"error"}
        for key, value in data.items():
            if key in _RESPONSE_WRAPPER_KEYS:
                continue
            if key not in valid_fields:
                rejected.append({"key": key, "reason": "unknown field"})
                continue

            field_obj = valid_fields[key]
            current = getattr(self, key)

            # Type coercion
            ftype = field_obj.type
            is_list = (ftype is list) or (isinstance(ftype, str) and ftype.startswith('list')) \
                or (get_origin(ftype) is list)
            is_dict = (ftype is dict) or (isinstance(ftype, str) and ftype.startswith('dict')) \
                or (get_origin(ftype) is dict)
            try:
                if ftype == 'bool' or ftype is bool:
                    if isinstance(value, str):
                        value = _bool(value)
                    else:
                        value = bool(value)
                elif ftype == 'int' or ftype is int:
                    if value is None:
                        rejected.append({"key": key, "reason": "null not allowed for int"})
                        continue
                    value = int(value)
                elif ftype == 'str' or ftype is str:
                    if value is None:
                        rejected.append({"key": key, "reason": "null not allowed for str"})
                        continue
                    value = str(value)
                elif is_dict:
                    if not isinstance(value, dict):
                        rejected.append({"key": key, "reason": "expected dict"})
                        continue
                    # ENABLED_QUALITY_OPTIONS: keys must be known
                    # resolutions, values must be lists of ints that
                    # intersect the canonical bitrate set for that tier.
                    # Resolution-only tiers (360p / 240p / 144p) always
                    # store [] -- their bitrate value is ignored on
                    # render but normalising here keeps config.json
                    # tidy.
                    if key == 'ENABLED_QUALITY_OPTIONS':
                        cleaned: dict[str, list[int]] = {}
                        for res, kbps_list in value.items():
                            if res not in RESOLUTION_ORDER:
                                continue
                            tier_bitrates = set(QUALITY_TIERS[res]['bitrates_kbps'])
                            if not tier_bitrates:
                                cleaned[res] = []
                                continue
                            allowed: list[int] = []
                            for raw in (kbps_list or []):
                                try:
                                    kbps = int(raw)
                                except (ValueError, TypeError):
                                    continue
                                if kbps in tier_bitrates and kbps not in allowed:
                                    allowed.append(kbps)
                            cleaned[res] = allowed
                        value = cleaned
                elif is_list:
                    if isinstance(value, list):
                        value = [str(x).strip() for x in value if str(x).strip()]
                    elif isinstance(value, str):
                        value = [s.strip() for s in value.split(',') if s.strip()]
                    else:
                        rejected.append({"key": key, "reason": "expected list or comma-separated string"})
                        continue
            except (ValueError, TypeError) as e:
                rejected.append({"key": key, "reason": f"coercion failed: {e}"})
                continue

            if value != current:
                setattr(self, key, value)
                changed.append(key)

        return changed, rejected

    @classmethod
    def field_metadata(cls) -> list:
        """Return field info for the admin UI"""
        sections = {
            'Auth': ['REQUIRE_LOGIN'],
            'Playback': ['FORCE_TRANSCODE', 'BINGE_WATCH_ENABLED', 'BINGE_WATCH_COUNTDOWN_SECONDS'],
            'Quality': ['ENABLED_QUALITY_OPTIONS'],
            'Logging': ['LOG_LEVEL', 'LOG_TO_FILE', 'LOG_FILE', 'LOG_FORMAT', 'LOG_MAX_SIZE', 'CONSOLE_LOG_LEVEL'],
            'Security': ['MAX_USERS_PER_PARTY', 'ENABLE_HLS_TOKEN_VALIDATION', 'HLS_TOKEN_EXPIRY',
                         'ENABLE_RATE_LIMITING', 'RATE_LIMIT_PARTY_CREATION', 'RATE_LIMIT_API_CALLS'],
            'Session': ['STATIC_SESSION_ENABLED', 'STATIC_SESSION_ID'],
            'Late Join Vote': ['LATE_JOIN_VOTE_ENABLED', 'LATE_JOIN_VOTE_TIMEOUT_SECONDS',
                                'LATE_JOIN_VOTE_COOLDOWN_SECONDS'],
        }
        result = []
        for section, keys in sections.items():
            for key in keys:
                f = next((fd for fd in fields(cls) if fd.name == key), None)
                if f:
                    result.append({
                        'name': f.name,
                        'type': f.type.__name__ if hasattr(f.type, '__name__') else str(f.type),
                        'section': section,
                        'default': f.default if f.default is not f.default_factory else None,
                    })
        return result


class Config:
    """
    Facade combining EnvConfig and RuntimeConfig.
    All existing config.X accesses work via __getattr__.
    """

    def __init__(self, env: EnvConfig, runtime: RuntimeConfig):
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, '_env', env)
        object.__setattr__(self, '_runtime', runtime)
        object.__setattr__(self, '_lock', threading.Lock())

    def __getattr__(self, name: str):
        # Check runtime first (mutable settings), then env (frozen)
        runtime = object.__getattribute__(self, '_runtime')
        if hasattr(runtime, name):
            return getattr(runtime, name)

        env = object.__getattribute__(self, '_env')
        if hasattr(env, name):
            return getattr(env, name)

        raise AttributeError(f"Config has no setting '{name}'")

    @classmethod
    def from_env(cls) -> 'Config':
        env = EnvConfig.from_env()
        runtime = RuntimeConfig.from_file()
        return cls(env, runtime)

    def update_runtime(self, data: dict) -> tuple[list, list]:
        """Update runtime settings, persist to config.json.

        Returns (changed_field_names, rejected_entries). rejected is a
        list of {key, reason} dicts describing values dropped due to
        wrong shape / failed coercion; surfaced by the admin router so
        the UI can tell the operator "Saved (but HLS_TOKEN_EXPIRY was
        not applied: expected int)" instead of silently pretending
        the change stuck.
        """
        lock = object.__getattribute__(self, '_lock')
        runtime = object.__getattribute__(self, '_runtime')
        with lock:
            changed, rejected = runtime.update_from_dict(data)
            if changed:
                runtime.save()
            return changed, rejected

    def get_runtime_dict(self) -> dict:
        """Get all runtime settings as a dict (for admin API)"""
        runtime = object.__getattribute__(self, '_runtime')
        return runtime.to_dict()

    def validate_for_startup(self) -> None:
        """Reject unsafe boot configuration when production mode is explicit."""
        if self.APP_ENV not in {'development', 'production'}:
            raise ValueError("APP_ENV must be 'development' or 'production'")
        if self.APP_ENV != 'production':
            return
        if not self.SESSION_SECRET:
            raise ValueError('SESSION_SECRET is required in production')
        if len(self.SESSION_SECRET) < 32:
            raise ValueError('SESSION_SECRET must be at least 32 characters in production')
        if not self.SESSION_COOKIE_SECURE:
            raise ValueError('SESSION_COOKIE_SECURE must be true in production')
        if not self.CORS_ALLOWED_ORIGINS or '*' in self.CORS_ALLOWED_ORIGINS:
            raise ValueError('CORS_ALLOWED_ORIGINS must be explicit in production')
        if not self.EMBY_API_KEY:
            raise ValueError('EMBY_API_KEY is required in production')
        emby_url = urlsplit(self.EMBY_SERVER_URL)
        if emby_url.scheme not in {'http', 'https'} or not emby_url.hostname:
            raise ValueError('EMBY_SERVER_URL must be a valid HTTP(S) URL in production')
        if not self.ENABLE_HLS_TOKEN_VALIDATION:
            raise ValueError('HLS token validation must be enabled in production')
