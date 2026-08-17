"""
Configuration for Emby Watch Party application

Two tiers:
- EnvConfig: frozen, loaded from .env at boot (restart required to change)
- RuntimeConfig: mutable, loaded from config.json (hot-reloadable via admin panel)
- Config: facade combining both, backward compatible with config.X access
"""

import contextlib
import copy
import ipaddress
import json
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import get_origin
from urllib.parse import urlsplit

from dotenv import dotenv_values

from backend.src.quality import DEFAULT_ENABLED_OPTIONS, QUALITY_TIERS, RESOLUTION_ORDER


def _bool(value: str) -> bool:
    """Convert env string to bool"""
    return value.lower() in ("true", "1", "yes")


CONFIG_JSON_PATH = Path(__file__).parent.parent.parent / "config.json"
_APP_PREFIX_RE = re.compile(r"(?:/[A-Za-z0-9][A-Za-z0-9._~-]*)+")
_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
# Docker Compose service and container names may legally contain underscores,
# and Docker's embedded DNS resolves them, so `http://emby_server:8096` is a
# real upstream address even though RFC 1123 forbids the character. This stays
# separate from `_DNS_LABEL_RE` because it is only correct for addresses this
# server dials itself: a browser cannot originate from such a host, so CORS
# origins keep the strict form.
_SERVICE_LABEL_RE = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?")
_PRIVATE_ENV_FIELDS = frozenset(
    {
        "EMBY_WATCHPARTY_X_DEV_HOST",
        "EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK",
    }
)
# Retired in 3.0. One URL and one key now serve both providers, because the
# address and the credential were never provider-specific -- only
# MEDIA_SERVER_TYPE was. These are deliberately NOT read as fallbacks: an
# operator who upgrades without renaming would otherwise boot against the
# default localhost URL and get an empty library with no explanation, so the
# retired name is a boot error naming its replacement.
_RETIRED_PROVIDER_FIELDS: dict[str, str] = {
    "EMBY_SERVER_URL": "MEDIA_SERVER_URL",
    "JELLYFIN_SERVER_URL": "MEDIA_SERVER_URL",
    "EMBY_API_KEY": "MEDIA_SERVER_API_KEY",
    "JELLYFIN_API_KEY": "MEDIA_SERVER_API_KEY",
}
_RATE_LIMIT_FIELDS = frozenset(
    {
        "RATE_LIMIT_PARTY_CREATION",
        "RATE_LIMIT_API_CALLS",
        "RATE_LIMIT_LOGIN",
        "RATE_LIMIT_AVATAR_RECOVERY",
        "RATE_LIMIT_CHAT",
        "RATE_LIMIT_SOCKET_CONNECTIONS",
    }
)


def _valid_url_host(hostname: str | None, *, allow_service_names: bool = False) -> bool:
    if not hostname or "*" in hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("ascii").decode("ascii")
    except UnicodeError:
        return False
    label = _SERVICE_LABEL_RE if allow_service_names else _DNS_LABEL_RE
    return len(ascii_hostname) <= 253 and all(
        label.fullmatch(part) for part in ascii_hostname.split(".")
    )


def _valid_http_url(value: str, *, origin: bool) -> bool:
    if not value or any(ord(char) <= 32 or char == "\\" for char in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not _valid_url_host(parsed.hostname, allow_service_names=not origin)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
        or (port is not None and port < 1)
    ):
        return False
    return not origin or not parsed.path


@dataclass(frozen=True)
class EnvConfig:
    """Boot-essential settings from .env (restart required)"""

    WATCH_PARTY_BIND: str
    WATCH_PARTY_PORT: int
    APP_PREFIX: str
    SESSION_EXPIRY: int
    # Declared before the URL and the key so the three read as one
    # decision, matching deploy/schema.json: the address and the
    # credential are not provider-specific, this is the only field that
    # names a provider. It carries no class-level default, because the
    # field order that puts it here forbids one, and because a silent
    # default would be an implicit provider guess -- the thing 3.0
    # removed. `from_env` still resolves an absent value to "emby".
    MEDIA_SERVER_TYPE: str
    MEDIA_SERVER_URL: str
    MEDIA_SERVER_API_KEY: str
    APP_ENV: str
    SESSION_SECRET: str
    SESSION_COOKIE_SECURE: bool
    CORS_ALLOWED_ORIGINS: tuple[str, ...]
    TRUSTED_PROXY_CIDRS: tuple[str, ...]
    ENABLE_HLS_TOKEN_VALIDATION: bool = True
    # Tri-state deliberately. None means "never declared", which is a
    # different thing from False, "declared as directly exposed".
    #
    # Rate limiting keys on the address the connection came from. Behind
    # a reverse proxy that is the proxy for every viewer, so without
    # TRUSTED_PROXY_CIDRS the whole deployment shares one bucket: 5 party
    # creations per hour and 30 socket connects per minute, for everyone,
    # silently. But an empty CIDR list is *correct* for a directly
    # exposed deployment, where trusting a forwarded header would let
    # anyone forge their own bucket. Emptiness alone therefore cannot be
    # validated, and no code can infer the topology, since "every request
    # arrives from 172.18.0.5" looks identical to a legitimate
    # single-source deployment. Making the operator state it is what
    # turns the ambiguity into a contradiction we can catch.
    BEHIND_PROXY: bool | None = None

    @classmethod
    def from_env(
        cls,
        project_root: Path | None = None,
        *,
        legacy_hls_validation: bool = True,
        errors: dict[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "EnvConfig":
        """Resolve boot settings from the process environment and .env.

        `environ` overrides the process environment. It exists so callers
        that only want to *predict* a boot -- the migration preflight --
        can resolve exactly what this loader would resolve, instead of
        re-implementing precedence and .env parsing and drifting from it.
        """
        root = Path(project_root or Path(__file__).parent.parent.parent)
        process_env: Mapping[str, str] = os.environ if environ is None else environ
        dot_env = {
            key: value for key, value in dotenv_values(root / ".env").items() if value is not None
        }

        defaults: dict[str, object] = {
            "WATCH_PARTY_BIND": "0.0.0.0",
            "WATCH_PARTY_PORT": "5000",
            "APP_PREFIX": "",
            "SESSION_EXPIRY": "86400",
            "MEDIA_SERVER_URL": "http://localhost:8096",
            "MEDIA_SERVER_API_KEY": "",
            "MEDIA_SERVER_TYPE": "emby",
            "APP_ENV": "development",
            "SESSION_SECRET": "",
            "SESSION_COOKIE_SECURE": "false",
            "CORS_ALLOWED_ORIGINS": "*",
            "TRUSTED_PROXY_CIDRS": "",
            "ENABLE_HLS_TOKEN_VALIDATION": legacy_hls_validation,
            "BEHIND_PROXY": "false",
        }

        def value(name: str) -> object:
            if name in process_env:
                return process_env[name]
            if name in dot_env:
                return dot_env[name]
            return defaults[name]

        def csv(name: str) -> tuple[str, ...]:
            raw_value = value(name)
            if isinstance(raw_value, list):
                return tuple(str(item).strip() for item in raw_value if str(item).strip())
            return tuple(item.strip() for item in str(raw_value).split(",") if item.strip())

        def integer(name: str, fallback: int) -> int:
            try:
                return int(str(value(name)))
            except (TypeError, ValueError):
                if errors is not None:
                    errors[name] = "Must be an integer"
                return fallback

        def boolean(name: str, fallback: bool) -> bool:
            raw_value = value(name)
            if isinstance(raw_value, bool):
                return raw_value
            normalized = str(raw_value).strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
            if errors is not None:
                errors[name] = "Must be true or false"
            return fallback

        def declared(name: str) -> bool:
            """True when a value was supplied rather than defaulted."""
            return name in process_env or name in dot_env

        return cls(
            WATCH_PARTY_BIND=str(value("WATCH_PARTY_BIND")),
            WATCH_PARTY_PORT=integer("WATCH_PARTY_PORT", 5000),
            APP_PREFIX=str(value("APP_PREFIX")).rstrip("/"),
            SESSION_EXPIRY=integer("SESSION_EXPIRY", 86400),
            MEDIA_SERVER_TYPE=str(value("MEDIA_SERVER_TYPE")).strip().lower(),
            MEDIA_SERVER_URL=str(value("MEDIA_SERVER_URL")).strip(),
            MEDIA_SERVER_API_KEY=str(value("MEDIA_SERVER_API_KEY")).strip(),
            APP_ENV=str(value("APP_ENV")).strip().lower(),
            SESSION_SECRET=str(value("SESSION_SECRET")).strip(),
            SESSION_COOKIE_SECURE=boolean("SESSION_COOKIE_SECURE", False),
            CORS_ALLOWED_ORIGINS=csv("CORS_ALLOWED_ORIGINS"),
            TRUSTED_PROXY_CIDRS=csv("TRUSTED_PROXY_CIDRS"),
            ENABLE_HLS_TOKEN_VALIDATION=boolean(
                "ENABLE_HLS_TOKEN_VALIDATION", legacy_hls_validation
            ),
            BEHIND_PROXY=boolean("BEHIND_PROXY", False) if declared("BEHIND_PROXY") else None,
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
    LOG_LEVEL: str = "INFO"
    LOG_TO_FILE: bool = True
    LOG_FILE: str = "logs/emby-watchparty.log"
    LOG_FORMAT: str = "rsyslog"
    LOG_MAX_SIZE: int = 10
    CONSOLE_LOG_LEVEL: str = "WARNING"

    # Security
    MAX_USERS_PER_PARTY: int = 0
    ENABLE_HLS_TOKEN_VALIDATION: bool = True
    HLS_TOKEN_EXPIRY: int = 86400
    ENABLE_RATE_LIMITING: bool = True
    RATE_LIMIT_PARTY_CREATION: str = "5 per hour"
    RATE_LIMIT_API_CALLS: str = "1000 per minute"
    RATE_LIMIT_LOGIN: str = "10 per 15 minutes"
    RATE_LIMIT_AVATAR_RECOVERY: str = "10 per hour"
    RATE_LIMIT_CHAT: str = "5 per 3 seconds"
    RATE_LIMIT_SOCKET_CONNECTIONS: str = "30 per minute"

    # Session
    STATIC_SESSION_ENABLED: bool = False
    STATIC_SESSION_ID: str = "PARTY"

    # Late joiner vote
    LATE_JOIN_VOTE_ENABLED: bool = True
    LATE_JOIN_VOTE_TIMEOUT_SECONDS: int = 20
    # Cooldown after a failed/cancelled vote before a new late join is
    # allowed. Prevents a malicious user from spamming the party URL to
    # repeatedly pop vote modals on existing watchers.
    LATE_JOIN_VOTE_COOLDOWN_SECONDS: int = 30

    @classmethod
    def from_file(cls, path: Path = CONFIG_JSON_PATH) -> "RuntimeConfig":
        """Load from config.json, falling back to defaults for missing fields.

        If config.json is corrupted (truncated / not valid JSON) we still
        return defaults, but we side-move the bad file to
        `<path>.corrupt-<timestamp>` and log at warning level so the
        operator has both a signal AND a recoverable copy. Previously
        this was a silent `pass` -- the next admin save would then
        overwrite config.json with defaults, permanently losing every
        prior admin tuning.
        """
        import logging as _logging
        import shutil
        import time as _t

        instance = cls()
        if path.exists():
            try:
                with path.open() as f:
                    data = json.load(f)
                instance.update_from_dict(data)
            except json.JSONDecodeError as e:
                backup_path = path.with_name(f"{path.name}.corrupt-{int(_t.time())}")
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
        """Persist current runtime settings, atomically where the layout allows.

        Write to a sibling temp file and os.replace() onto the target.
        Prevents the crash-mid-write case where truncating config.json
        via `open(path, 'w')` and then dying (OOM, power-loss, exception
        during json.dump) leaves a partial or empty file, which
        from_file() then silently swallowed as "use defaults", erasing
        every admin-tuned setting.

        When config.json is bind-mounted as a single file, the layout both
        the README and docker-compose.yml.example recommend, the target is a
        mount point and rename(2) onto it fails with EBUSY. No atomic path
        exists there: the point of that mount is that the host's inode must
        survive, so replacing it is exactly what must not happen. Fall back
        to writing through the existing inode, in one write() followed by
        truncate() so a concurrent reader sees old or new rather than a
        half-empty file, and keep the temp file until that write succeeds so
        a failure cannot leave the target truncated.
        """
        import errno
        import os
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory so os.replace() is atomic (rename across
        # filesystems can partial-succeed). NamedTemporaryFile with
        # delete=False so we control the final rename ourselves.
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(self.to_dict(), tmp, indent=2)
            tmp.flush()
            with contextlib.suppress(OSError):
                os.fsync(tmp.fileno())
            tmp_name = tmp.name
        try:
            Path(tmp_name).replace(path)
        except OSError as e:
            # EBUSY is the bind-mounted single file. EXDEV should not reach
            # here because the temp file is a sibling, but a target that is
            # itself a mount of another filesystem reports it, and the same
            # write-through recovery is correct for both.
            if e.errno not in (errno.EBUSY, errno.EXDEV):
                raise
            payload = Path(tmp_name).read_bytes()
            # "r+b" rather than "wb": opening for write truncates first and
            # reopens the same inode, which would hand a reader an empty file
            # for the length of the write.
            with path.open("r+b") as dst:
                dst.write(payload)
                dst.truncate()
                dst.flush()
                with contextlib.suppress(OSError):
                    os.fsync(dst.fileno())
        finally:
            # After a successful replace the temp file is already gone, so
            # this is a no-op. It matters on every other path: without it a
            # failed save leaves a config.json.*.tmp behind on each attempt.
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink()

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
        response_wrapper_keys = {"error"}
        for key, value in data.items():
            if key in response_wrapper_keys:
                continue
            if key not in valid_fields:
                rejected.append({"key": key, "reason": "unknown field"})
                continue

            field_obj = valid_fields[key]
            current = getattr(self, key)

            # Type coercion
            ftype = field_obj.type
            is_list = (
                (ftype is list)
                or (isinstance(ftype, str) and ftype.startswith("list"))
                or (get_origin(ftype) is list)
            )
            is_dict = (
                (ftype is dict)
                or (isinstance(ftype, str) and ftype.startswith("dict"))
                or (get_origin(ftype) is dict)
            )
            try:
                if ftype == "bool" or ftype is bool:
                    value = _bool(value) if isinstance(value, str) else bool(value)
                elif ftype == "int" or ftype is int:
                    if value is None:
                        rejected.append({"key": key, "reason": "null not allowed for int"})
                        continue
                    value = int(value)
                elif ftype == "str" or ftype is str:
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
                    if key == "ENABLED_QUALITY_OPTIONS":
                        cleaned: dict[str, list[int]] = {}
                        for res, kbps_list in value.items():
                            if res not in RESOLUTION_ORDER:
                                continue
                            tier_bitrates = set(QUALITY_TIERS[res]["bitrates_kbps"])
                            if not tier_bitrates:
                                cleaned[res] = []
                                continue
                            allowed: list[int] = []
                            for raw in kbps_list or []:
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
                        value = [s.strip() for s in value.split(",") if s.strip()]
                    else:
                        rejected.append(
                            {"key": key, "reason": "expected list or comma-separated string"}
                        )
                        continue
            except (ValueError, TypeError) as e:
                rejected.append({"key": key, "reason": f"coercion failed: {e}"})
                continue

            if key in _RATE_LIMIT_FIELDS:
                from backend.src.rate_limit import parse_rate

                try:
                    parse_rate(value)
                except ValueError as e:
                    rejected.append({"key": key, "reason": str(e)})
                    continue

            if value != current:
                setattr(self, key, value)
                changed.append(key)

        return changed, rejected

    @classmethod
    def field_metadata(cls) -> list:
        """Return field info for the admin UI"""
        sections = {
            "Auth": ["REQUIRE_LOGIN"],
            "Playback": ["FORCE_TRANSCODE", "BINGE_WATCH_ENABLED", "BINGE_WATCH_COUNTDOWN_SECONDS"],
            "Quality": ["ENABLED_QUALITY_OPTIONS"],
            "Logging": [
                "LOG_LEVEL",
                "LOG_TO_FILE",
                "LOG_FILE",
                "LOG_FORMAT",
                "LOG_MAX_SIZE",
                "CONSOLE_LOG_LEVEL",
            ],
            "Security": [
                "MAX_USERS_PER_PARTY",
                "HLS_TOKEN_EXPIRY",
                "ENABLE_RATE_LIMITING",
                "RATE_LIMIT_PARTY_CREATION",
                "RATE_LIMIT_API_CALLS",
                "RATE_LIMIT_LOGIN",
                "RATE_LIMIT_AVATAR_RECOVERY",
                "RATE_LIMIT_CHAT",
                "RATE_LIMIT_SOCKET_CONNECTIONS",
            ],
            "Session": ["STATIC_SESSION_ENABLED", "STATIC_SESSION_ID"],
            "Late Join Vote": [
                "LATE_JOIN_VOTE_ENABLED",
                "LATE_JOIN_VOTE_TIMEOUT_SECONDS",
                "LATE_JOIN_VOTE_COOLDOWN_SECONDS",
            ],
        }
        result = []
        for section, keys in sections.items():
            for key in keys:
                f = next((fd for fd in fields(cls) if fd.name == key), None)
                if f:
                    result.append(
                        {
                            "name": f.name,
                            "type": f.type.__name__ if hasattr(f.type, "__name__") else str(f.type),
                            "section": section,
                            "default": f.default if f.default is not f.default_factory else None,
                        }
                    )
        return result


class Config:
    """
    Facade combining EnvConfig and RuntimeConfig.
    All existing config.X accesses work via __getattr__.
    """

    def __init__(
        self,
        env: EnvConfig,
        runtime: RuntimeConfig,
        *,
        load_errors: dict[str, str] | None = None,
        private_env: dict[str, str] | None = None,
        retired_fields: set[str] | None = None,
    ):
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_lock", threading.Lock())
        object.__setattr__(self, "_load_errors", dict(load_errors or {}))
        object.__setattr__(self, "_private_env", dict(private_env or {}))
        object.__setattr__(self, "_retired_fields", set(retired_fields or ()))

    def __getattr__(self, name: str):
        env = object.__getattribute__(self, "_env")
        if name == "ENABLE_HLS_TOKEN_VALIDATION":
            return env.ENABLE_HLS_TOKEN_VALIDATION
        # Check runtime first (mutable settings), then env (frozen)
        runtime = object.__getattribute__(self, "_runtime")
        if hasattr(runtime, name):
            return getattr(runtime, name)

        if hasattr(env, name):
            return getattr(env, name)

        raise AttributeError(f"Config has no setting '{name}'")

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Config":
        root = Path(project_root or Path(__file__).parent.parent.parent)
        runtime = RuntimeConfig.from_file(root / "config.json")
        dot_env = dotenv_values(root / ".env")
        private_env = {
            name: str(os.environ[name] if name in os.environ else dot_env[name])
            for name in _PRIVATE_ENV_FIELDS
            if name in os.environ or dot_env.get(name) is not None
        }
        load_errors: dict[str, str] = {}
        env = EnvConfig.from_env(
            root,
            legacy_hls_validation=runtime.ENABLE_HLS_TOKEN_VALIDATION,
            errors=load_errors,
        )
        return cls(
            env,
            runtime,
            load_errors=load_errors,
            private_env=private_env,
            retired_fields={
                name
                for name in _RETIRED_PROVIDER_FIELDS
                if name in os.environ or dot_env.get(name) is not None
            },
        )

    def update_runtime(self, data: dict) -> tuple[list, list]:
        """Update runtime settings, persist to config.json.

        Returns (changed_field_names, rejected_entries). rejected is a
        list of {key, reason} dicts describing values dropped due to
        wrong shape / failed coercion; surfaced by the admin router so
        the UI can tell the operator "Saved (but HLS_TOKEN_EXPIRY was
        not applied: expected int)" instead of silently pretending
        the change stuck.
        """
        lock = object.__getattribute__(self, "_lock")
        runtime = object.__getattribute__(self, "_runtime")
        with lock:
            payload = dict(data)
            rejected: list[dict] = []
            if "ENABLE_HLS_TOKEN_VALIDATION" in payload:
                payload.pop("ENABLE_HLS_TOKEN_VALIDATION")
                rejected.append(
                    {
                        "key": "ENABLE_HLS_TOKEN_VALIDATION",
                        "reason": "boot setting; restart required",
                    }
                )
            # One request can update many scalar and collection fields. Keep a
            # deep snapshot so any persistence failure restores all of them;
            # callers must never observe a partially applied failed save.
            original_values = copy.deepcopy(runtime.to_dict())
            try:
                changed, runtime_rejected = runtime.update_from_dict(payload)
                rejected.extend(runtime_rejected)
                if changed:
                    runtime.save()
            except Exception:
                for key, value in original_values.items():
                    setattr(runtime, key, value)
                raise
            return changed, rejected

    def get_runtime_dict(self) -> dict:
        """Get all runtime settings as a dict (for admin API)"""
        runtime = object.__getattribute__(self, "_runtime")
        values = runtime.to_dict()
        values.pop("ENABLE_HLS_TOKEN_VALIDATION", None)
        return values

    def _private_env_value(self, name: str) -> str:
        """Return a boot-loaded private setting that must never reach admin APIs."""
        if name not in _PRIVATE_ENV_FIELDS:
            raise KeyError(name)
        return object.__getattribute__(self, "_private_env").get(name, "")

    def validate_for_startup(self) -> None:
        """Reject unsafe boot configuration when production mode is explicit."""
        errors = self.startup_errors()
        if errors:
            field_name, message = next(iter(errors.items()))
            raise ValueError(f"{field_name}: {message}")

    def startup_errors(self) -> dict[str, str]:
        """Return safe field-level boot errors without including submitted values."""
        errors = dict(object.__getattribute__(self, "_load_errors"))
        for name in sorted(object.__getattribute__(self, "_retired_fields")):
            errors.setdefault(
                name,
                f"was replaced by {_RETIRED_PROVIDER_FIELDS[name]} in 3.0; "
                "rename it and remove the old name",
            )
        if self.APP_ENV not in {"development", "production"}:
            errors.setdefault("APP_ENV", "must be 'development' or 'production'")
        if self.MEDIA_SERVER_TYPE not in {"emby", "jellyfin"}:
            errors.setdefault("MEDIA_SERVER_TYPE", "must be 'emby' or 'jellyfin'")
        if not (1 <= self.WATCH_PARTY_PORT <= 65535):
            errors.setdefault("WATCH_PARTY_PORT", "must be between 1 and 65535")
        prefix = self.APP_PREFIX
        if prefix and (len(prefix) > 256 or _APP_PREFIX_RE.fullmatch(prefix) is None):
            errors.setdefault(
                "APP_PREFIX",
                "must use slash-prefixed letters, numbers, dots, underscores, tildes, or hyphens",
            )
        for cidr in self.TRUSTED_PROXY_CIDRS:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                errors.setdefault("TRUSTED_PROXY_CIDRS", "must contain valid IP networks")
                break
        if not _valid_http_url(self.MEDIA_SERVER_URL, origin=False):
            errors.setdefault("MEDIA_SERVER_URL", "must be a valid HTTP(S) URL")
        # Unconditional: the operator has stated they sit behind a proxy
        # and then not said which addresses those proxies are, so the
        # forwarded header is discarded and every viewer keys onto the
        # proxy's address. That is a self-contradiction in any
        # environment, not just production.
        if self.BEHIND_PROXY and not self.TRUSTED_PROXY_CIDRS:
            errors.setdefault(
                "TRUSTED_PROXY_CIDRS",
                "is required when BEHIND_PROXY=true, or every client shares one rate-limit bucket",
            )
        if self.APP_ENV == "production":
            # Production only. Development defaults to a direct
            # deployment, which is what running it locally is.
            if self.BEHIND_PROXY is None:
                errors.setdefault(
                    "BEHIND_PROXY",
                    "must be declared: true if a reverse proxy terminates client connections, "
                    "false if this server is exposed directly",
                )
            if not self.SESSION_SECRET:
                errors.setdefault("SESSION_SECRET", "is required in production")
            elif len(self.SESSION_SECRET) < 32:
                errors.setdefault("SESSION_SECRET", "must be at least 32 characters in production")
            if not self.SESSION_COOKIE_SECURE:
                errors.setdefault("SESSION_COOKIE_SECURE", "must be true in production")
            if not self.CORS_ALLOWED_ORIGINS or "*" in self.CORS_ALLOWED_ORIGINS:
                errors.setdefault("CORS_ALLOWED_ORIGINS", "must be explicit in production")
            else:
                for origin in self.CORS_ALLOWED_ORIGINS:
                    if not _valid_http_url(origin, origin=True):
                        errors.setdefault(
                            "CORS_ALLOWED_ORIGINS", "must contain valid HTTP(S) origins"
                        )
                        break
            if not self.MEDIA_SERVER_API_KEY:
                errors.setdefault("MEDIA_SERVER_API_KEY", "is required in production")
            if not self.ENABLE_HLS_TOKEN_VALIDATION:
                errors.setdefault("ENABLE_HLS_TOKEN_VALIDATION", "must be enabled in production")
        return errors
