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
from typing import Optional, get_origin

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

    @classmethod
    def from_env(cls) -> 'EnvConfig':
        env_path = Path(__file__).parent.parent.parent / '.env'
        load_dotenv(env_path)

        return cls(
            WATCH_PARTY_BIND=os.getenv('WATCH_PARTY_BIND', '0.0.0.0'),
            WATCH_PARTY_PORT=int(os.getenv('WATCH_PARTY_PORT', '5000')),
            APP_PREFIX=os.getenv('APP_PREFIX', '').rstrip('/'),
            SESSION_EXPIRY=int(os.getenv('SESSION_EXPIRY', '86400')),
            EMBY_SERVER_URL=os.getenv('EMBY_SERVER_URL', 'http://localhost:8096'),
            EMBY_API_KEY=os.getenv('EMBY_API_KEY', ''),
        )


@dataclass
class RuntimeConfig:
    """Runtime settings from config.json (hot-reloadable)"""

    # Auth gating.
    # True: party creation requires Emby credentials (creator becomes host).
    # False: anyone can create a party; any member can later log in to host.
    REQUIRE_LOGIN: bool = False

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
        """Load from config.json, falling back to defaults for missing fields"""
        instance = cls()
        if path.exists():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                instance.update_from_dict(data)
            except (json.JSONDecodeError, OSError):
                pass
        return instance

    def save(self, path: Path = CONFIG_JSON_PATH):
        """Persist current runtime settings to config.json"""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def update_from_dict(self, data: dict) -> list:
        """Apply validated changes. Returns list of changed field names."""
        changed = []
        valid_fields = {f.name: f for f in fields(self)}

        for key, value in data.items():
            if key not in valid_fields:
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
                    value = int(value)
                elif ftype == 'str' or ftype is str:
                    value = str(value)
                elif is_dict:
                    if not isinstance(value, dict):
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
                        continue
            except (ValueError, TypeError):
                continue

            if value != current:
                setattr(self, key, value)
                changed.append(key)

        return changed

    @classmethod
    def field_metadata(cls) -> list:
        """Return field info for the admin UI"""
        sections = {
            'Auth': ['REQUIRE_LOGIN'],
            'Playback': ['FORCE_TRANSCODE'],
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

    def update_runtime(self, data: dict) -> list:
        """Update runtime settings, persist to config.json. Returns changed field names."""
        lock = object.__getattribute__(self, '_lock')
        runtime = object.__getattribute__(self, '_runtime')
        with lock:
            changed = runtime.update_from_dict(data)
            if changed:
                runtime.save()
            return changed

    def get_runtime_dict(self) -> dict:
        """Get all runtime settings as a dict (for admin API)"""
        runtime = object.__getattribute__(self, '_runtime')
        return runtime.to_dict()
