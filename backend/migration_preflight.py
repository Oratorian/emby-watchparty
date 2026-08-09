"""Read-only 2.1.x to 3.0 migration preflight.

The preflight predicts a 3.0 boot, so anything it decides must be decided the
way 3.0 decides it. Values are read with the same `dotenv_values` loader
`EnvConfig.from_env` uses, and the verdict comes from `Config.startup_errors`
itself rather than a second opinion assembled here. A preflight that parses or
validates independently is a twin path, and a twin path that drifts hands the
operator a clean bill for a configuration that will not serve.

Read-only is a hard constraint: this module never routes through
`Config.from_env`, because that calls `RuntimeConfig.from_file`, which
side-moves a corrupt `config.json` to `config.json.corrupt-<timestamp>`.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.rate_limit import parse_rate

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Fields this report resolves and echoes by name. Kept narrow on purpose: the
# .env values it selects are the only ones that can reach the output, so a
# secret cannot be printed by accident. The boot verdict does NOT come from
# this set -- `Config.startup_errors` sees every field regardless.
_BOOT_FIELDS = {
    "APP_PREFIX",
    "BEHIND_PROXY",
    "TRUSTED_PROXY_CIDRS",
    "ENABLE_HLS_TOKEN_VALIDATION",
    "SESSION_EXPIRY",
}
_RATE_DEFAULTS = {
    "RATE_LIMIT_PARTY_CREATION": "5 per hour",
    "RATE_LIMIT_API_CALLS": "1000 per minute",
    "RATE_LIMIT_LOGIN": "10 per 15 minutes",
    "RATE_LIMIT_AVATAR_RECOVERY": "10 per hour",
    "RATE_LIMIT_CHAT": "5 per 3 seconds",
    "RATE_LIMIT_SOCKET_CONNECTIONS": "30 per minute",
}
_WORKER_FIELDS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "WORKERS")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.incomplete = False

    def error(self, message: str, *, incomplete: bool = False) -> None:
        self.lines.append(f"ERROR: {message}")
        self.incomplete = self.incomplete or incomplete

    def action(self, message: str) -> None:
        self.lines.append(f"REQUIRED ACTION: {message}")

    def info(self, message: str) -> None:
        self.lines.append(f"INFO: {message}")


def _read_dotenv(path: Path, report: _Report) -> dict[str, str]:
    if not path.exists():
        report.info(".env not found; preserve the deployment's actual environment source")
        return {}
    if not path.is_file():
        report.error(".env is not a regular file", incomplete=True)
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        report.error(".env could not be read", incomplete=True)
        return {}

    # Structural scan only: report lines the loader will silently ignore, so a
    # setting the operator believes is applied does not vanish without comment.
    for number, original in enumerate(lines, start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            report.error(f".env line {number} is malformed", incomplete=True)
            continue
        if not _ENV_KEY.fullmatch(line.split("=", 1)[0].strip()):
            report.error(f".env line {number} has an invalid variable name", incomplete=True)

    # Values come from the loader the application itself uses. Splitting on '='
    # here as well is what made the two disagree: this file's parser kept
    # trailing ` # comment` text that python-dotenv strips, so a perfectly
    # bootable `BEHIND_PROXY=true  # nginx` was reported as malformed, and an
    # `ENABLE_HLS_TOKEN_VALIDATION=false  # disabled in 2.x` silently skipped
    # the one required action a production upgrade depends on.
    try:
        loaded = dotenv_values(path)
    except OSError:
        report.error(".env could not be read", incomplete=True)
        return {}
    return {
        key: value
        for key, value in loaded.items()
        if value is not None and key in _BOOT_FIELDS | set(_WORKER_FIELDS)
    }


def _read_legacy(path: Path, report: _Report) -> dict[str, object]:
    if not path.exists():
        report.info("config.json not found; legacy runtime settings will use defaults")
        return {}
    if not path.is_file():
        report.error("config.json is not a regular file", incomplete=True)
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        report.error("config.json is not valid JSON", incomplete=True)
        return {}
    except OSError:
        report.error("config.json could not be read", incomplete=True)
        return {}
    if not isinstance(value, dict):
        report.error("config.json must contain a JSON object", incomplete=True)
        return {}
    return value


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _effective(
    name: str,
    environ: Mapping[str, str],
    dotenv: Mapping[str, str],
    *,
    legacy: object | None = None,
    default: object,
) -> tuple[object, str]:
    if name in environ:
        return environ[name], "process environment"
    if name in dotenv:
        return dotenv[name], ".env"
    if legacy is not None:
        return legacy, "legacy config.json"
    return default, "default"


def _invalid_cidr_positions(raw: str) -> list[int]:
    """1-based positions of entries `Config.startup_errors` would reject.

    Split on commas only, exactly as `EnvConfig.from_env`'s `csv()` does, so a
    space- or semicolon-separated list arrives here as the single invalid token
    the application will also see. Reporting "is declared" for any non-empty
    string is what let `TRUSTED_PROXY_CIDRS=172.16.0.0/12 10.0.0.0/8` clear the
    preflight and then refuse to boot.
    """
    invalid: list[int] = []
    for index, entry in enumerate(
        (item.strip() for item in raw.split(",") if item.strip()), start=1
    ):
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            invalid.append(index)
    return invalid


def _startup_errors(
    root: Path,
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
    target: str,
) -> dict[str, str]:
    """Ask 3.0's own boot gate what it would reject, without touching disk.

    `Config.from_env` is deliberately not used: it calls
    `RuntimeConfig.from_file`, which copies a corrupt `config.json` aside.
    The caller therefore passes a `RuntimeConfig` already built from the JSON
    parsed here, and the env half comes from the real loader with the caller's
    environment injected. Both are pure reads.

    `startup_errors` gates its strictest rules on `APP_ENV`, so the config is
    evaluated as the environment the operator says they are migrating *to*.
    Asking "does your current APP_ENV pass" would answer the wrong question:
    a 2.1.x deployment that never set it reads as development and sails
    through every production rule it is about to meet.
    """
    load_errors: dict[str, str] = {}
    env = EnvConfig.from_env(
        root,
        legacy_hls_validation=runtime.ENABLE_HLS_TOKEN_VALIDATION,
        errors=load_errors,
        environ=environ,
    )
    config = Config(replace(env, APP_ENV=target), runtime, load_errors=load_errors)
    return config.startup_errors()


def _node_version() -> tuple[int, ...] | None:
    executable = shutil.which("node")
    if executable is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - executable resolved with shutil.which
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    return tuple(map(int, match.groups())) if match else None


def run_preflight(
    root: Path,
    *,
    target: str = "production",
    deployment: str = "docker",
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    python_version: Sequence[int] | None = None,
    node_version: Sequence[int] | None = None,
) -> tuple[int, str]:
    """Inspect migration inputs without invoking mutating config loaders."""
    report = _Report()
    root = root.resolve()
    env = dict(os.environ if environ is None else environ)
    dotenv = _read_dotenv(root / ".env", report)
    legacy = _read_legacy(root / "config.json", report)
    # Fields this report already gives a specific, actionable instruction for.
    # The boot gate below is authoritative but generic, so it only speaks for
    # the fields nothing here has already explained.
    handled: set[str] = set()

    # Built once, from the JSON already parsed above, and reused for both the
    # legacy value lookups and the boot gate. Applying config.json twice would
    # let the two copies answer differently, which is the whole failure mode
    # this module keeps running into.
    runtime = RuntimeConfig()
    runtime.update_from_dict(dict(legacy))

    behind_raw, behind_source = _effective("BEHIND_PROXY", env, dotenv, default="", legacy=None)
    behind = _boolean(behind_raw) if behind_source != "default" else None
    if behind is None:
        handled.add("BEHIND_PROXY")
        if behind_source == "default":
            report.action("Set BEHIND_PROXY=true or BEHIND_PROXY=false before starting 3.0")
        else:
            report.error("BEHIND_PROXY must be true or false")
    else:
        report.info(f"BEHIND_PROXY={'true' if behind else 'false'} ({behind_source})")

    cidrs, cidr_source = _effective("TRUSTED_PROXY_CIDRS", env, dotenv, default="", legacy=None)
    cidr_text = str(cidrs).strip()
    if behind and not cidr_text:
        handled.add("TRUSTED_PROXY_CIDRS")
        report.action(
            "Set TRUSTED_PROXY_CIDRS to the proxy network, for example "
            "TRUSTED_PROXY_CIDRS=172.16.0.0/12"
        )
    elif cidr_text:
        # `Config.startup_errors` parses every entry with ip_network in EVERY
        # environment, not just production, so an unparseable list is a boot
        # failure the operator gets no warning about unless it is caught here.
        invalid = _invalid_cidr_positions(cidr_text)
        if invalid:
            handled.add("TRUSTED_PROXY_CIDRS")
            positions = ", ".join(str(position) for position in invalid)
            report.error(
                f"TRUSTED_PROXY_CIDRS entry {positions} is not a valid IP network "
                f"(comma-separated position, {cidr_source})"
            )
            report.action(
                "Set TRUSTED_PROXY_CIDRS to a comma-separated list of IP networks, "
                "for example TRUSTED_PROXY_CIDRS=172.16.0.0/12,10.0.0.0/8; "
                "spaces and semicolons are not separators"
            )
        else:
            report.info(f"TRUSTED_PROXY_CIDRS is declared ({cidr_source})")
    elif behind is False:
        report.info("TRUSTED_PROXY_CIDRS is empty, correct for BEHIND_PROXY=false")

    # Resolve the legacy value the way RuntimeConfig resolves it, not with a
    # local coercion. `legacy.get(...)` returns None both for an absent key and
    # for an explicit JSON null, and `_effective` reads None as "not present",
    # so a null was reported as the default `true` while the runtime coerces it
    # to False. Presence is therefore tested on the key, and the value comes
    # from the same object the boot gate uses.
    legacy_hls = (
        runtime.ENABLE_HLS_TOKEN_VALIDATION if "ENABLE_HLS_TOKEN_VALIDATION" in legacy else None
    )
    hls_raw, hls_source = _effective(
        "ENABLE_HLS_TOKEN_VALIDATION",
        env,
        dotenv,
        legacy=legacy_hls,
        default=True,
    )
    hls = _boolean(hls_raw)
    if hls is None:
        handled.add("ENABLE_HLS_TOKEN_VALIDATION")
        report.error("ENABLE_HLS_TOKEN_VALIDATION must be true or false")
    else:
        report.info(f"ENABLE_HLS_TOKEN_VALIDATION={'true' if hls else 'false'} ({hls_source})")
        if target == "production" and not hls:
            handled.add("ENABLE_HLS_TOKEN_VALIDATION")
            report.action(
                "Set ENABLE_HLS_TOKEN_VALIDATION=true in the environment; "
                "production otherwise fails closed"
            )

    expiry_raw, expiry_source = _effective(
        "SESSION_EXPIRY", env, dotenv, default="86400", legacy=None
    )
    try:
        expiry = int(str(expiry_raw))
    except ValueError:
        handled.add("SESSION_EXPIRY")
        report.error("SESSION_EXPIRY must be an integer number of seconds")
    else:
        report.info(f"SESSION_EXPIRY={expiry} ({expiry_source})")
        if expiry != 1_209_600:
            report.info("Set SESSION_EXPIRY=1209600 to retain the old 14-day cookie behavior")

    # The authoritative verdict. Everything above explains one field in the
    # operator's own terms; this asks 3.0's boot gate what it would actually
    # refuse, so a field nobody thought to enumerate here cannot pass in
    # silence. Enumerating a subset by hand is what let a stock 2.1.x
    # production .env -- wildcard CORS, non-Secure cookies, no API key --
    # collect a clean report and then serve 503 on every route.
    # `startup_errors` returns field names and fixed messages only, never the
    # submitted value, so nothing here can echo a secret.
    boot_errors = _startup_errors(root, runtime, env, target)
    for name in sorted(boot_errors):
        if name in handled:
            continue
        report.action(f"{name} {boot_errors[name]} -- 3.0 will not start otherwise")
    if not boot_errors:
        report.info(f"3.0 boot validation passes for target={target}")

    # ENABLE_RATE_LIMITING is the master switch, and it carries over from
    # config.json untouched. Reporting six limits as "enforced in 3.0" without
    # reading it tells an operator who turned rate limiting off in the 2.1.x
    # admin panel that they are protected when nothing is throttled.
    rate_limiting = runtime.ENABLE_RATE_LIMITING
    if not rate_limiting:
        report.action(
            "ENABLE_RATE_LIMITING=false carries into 3.0; turn it on under "
            "Admin -> Security for any of the limits below to apply"
        )
    for name, default in _RATE_DEFAULTS.items():
        raw = legacy.get(name, default)
        source = "legacy config.json" if name in legacy else "default"
        if not isinstance(raw, str):
            report.error(f"{name} must be a rate string")
            continue
        try:
            parse_rate(raw)
        except ValueError:
            report.error(f"{name} has a malformed legacy value")
            continue
        state = (
            "this limit is enforced in 3.0"
            if rate_limiting
            else "not enforced: ENABLE_RATE_LIMITING=false in config.json"
        )
        report.info(f"{name}={raw} ({source}); {state}")

    worker_declared = False
    worker_valid = True
    for name in _WORKER_FIELDS:
        raw, source = _effective(name, env, dotenv, default="", legacy=None)
        if source == "default" or not str(raw).strip():
            continue
        worker_declared = True
        try:
            valid = int(str(raw)) == 1
        except ValueError:
            valid = False
        worker_valid = worker_valid and valid
    if not worker_declared:
        report.info("No worker override found; 3.0 supports exactly one application worker")
    elif worker_valid:
        report.info("Application worker count is 1")
    else:
        report.action("Run exactly one application worker; set worker count to 1")

    active_platform = (platform_name or sys.platform).lower()
    if active_platform.startswith("win"):
        report.info("Windows support is best effort; Docker/Linux is recommended")

    active_python = tuple(python_version or sys.version_info[:3])
    if deployment == "docker":
        report.info("Docker image supplies Python 3.12 and its frontend is built with Node 24")
    else:
        if not ((3, 12) <= active_python[:2] < (3, 13)):
            report.action("Use Python >=3.12,<3.13 and recreate the virtual environment")
        else:
            report.info(f"Python {'.'.join(map(str, active_python[:3]))} meets >=3.12,<3.13")
        active_node = tuple(node_version) if node_version is not None else _node_version()
        if active_node is None or active_node[:2] < (20, 19):
            report.action("Use Node >=20.19 when building the frontend from source")
        else:
            report.info(f"Node {'.'.join(map(str, active_node[:3]))} meets >=20.19")

    for relative, label in (
        (".env", "environment file"),
        ("config.json", "legacy runtime configuration"),
        ("data", "data directory"),
        ("images/avatars", "avatar directory"),
    ):
        state = "found" if (root / relative).exists() else "not found here"
        report.info(f"Preserve {relative} ({label}; {state}) and its volume mapping")
    report.action(
        "Confirm a full backup of .env, Compose configuration, config.json, data, avatars, "
        "and volume mappings before upgrade"
    )
    report.info("Keep the 2.1.x image and configuration until real playback validation passes")
    # Both probes live under APP_PREFIX: the healthy factory mounts every router
    # with prefix=prefix, and the setup app registers the prefixed paths behind
    # an unprefixed 503 catch-all. Printing them bare inverts the signal on a
    # subpath deployment -- the documented curl 404s against a perfectly healthy
    # upgrade, and against a broken one it hits the catch-all and reports 503,
    # "dead", exactly where these two lines promise to say "misconfigured".
    # app.py drops the prefix when the boot gate rejected it, so mirror that.
    raw_prefix, _ = _effective("APP_PREFIX", env, dotenv, default="", legacy=None)
    prefix = "" if "APP_PREFIX" in boot_errors else str(raw_prefix).rstrip("/")
    report.info(
        f"Healthy 3.0: {prefix}/api/health returns 200 ok and {prefix}/api/ready returns 200"
    )
    report.info(
        f"Invalid production config: {prefix}/api/health returns 200 setup_required, "
        f"{prefix}/api/ready returns 503, and other routes remain unavailable"
    )
    report.action(
        "Prepare rollback by restoring the full backup and previous image/configuration; "
        "do not delete legacy files"
    )

    return (1 if report.incomplete else 0), "\n".join(report.lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--target", choices=("production", "development"), default="production")
    parser.add_argument("--deployment", choices=("docker", "source"), default="docker")
    args = parser.parse_args(argv)
    code, output = run_preflight(
        args.root,
        target=args.target,
        deployment=args.deployment,
    )
    print(output, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
