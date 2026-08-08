"""Read-only 2.1.x to 3.0 migration preflight."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from backend.src.rate_limit import parse_rate

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_BOOT_FIELDS = {
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

    values: dict[str, str] = {}
    for number, original in enumerate(lines, start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            report.error(f".env line {number} is malformed", incomplete=True)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            report.error(f".env line {number} has an invalid variable name", incomplete=True)
            continue
        if key not in _BOOT_FIELDS and key not in _WORKER_FIELDS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


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

    behind_raw, behind_source = _effective("BEHIND_PROXY", env, dotenv, default="", legacy=None)
    behind = _boolean(behind_raw) if behind_source != "default" else None
    if behind is None:
        if behind_source == "default":
            report.action("Set BEHIND_PROXY=true or BEHIND_PROXY=false before starting 3.0")
        else:
            report.error("BEHIND_PROXY must be true or false")
    else:
        report.info(f"BEHIND_PROXY={'true' if behind else 'false'} ({behind_source})")

    cidrs, cidr_source = _effective("TRUSTED_PROXY_CIDRS", env, dotenv, default="", legacy=None)
    if behind and not str(cidrs).strip():
        report.action(
            "Set TRUSTED_PROXY_CIDRS to the proxy network, for example "
            "TRUSTED_PROXY_CIDRS=172.16.0.0/12"
        )
    elif str(cidrs).strip():
        report.info(f"TRUSTED_PROXY_CIDRS is declared ({cidr_source})")
    elif behind is False:
        report.info("TRUSTED_PROXY_CIDRS is empty, correct for BEHIND_PROXY=false")

    legacy_hls = legacy.get("ENABLE_HLS_TOKEN_VALIDATION")
    hls_raw, hls_source = _effective(
        "ENABLE_HLS_TOKEN_VALIDATION",
        env,
        dotenv,
        legacy=legacy_hls,
        default=True,
    )
    hls = _boolean(hls_raw)
    if hls is None:
        report.error("ENABLE_HLS_TOKEN_VALIDATION must be true or false")
    else:
        report.info(f"ENABLE_HLS_TOKEN_VALIDATION={'true' if hls else 'false'} ({hls_source})")
        if target == "production" and not hls:
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
        report.error("SESSION_EXPIRY must be an integer number of seconds")
    else:
        report.info(f"SESSION_EXPIRY={expiry} ({expiry_source})")
        if expiry != 1_209_600:
            report.info("Set SESSION_EXPIRY=1209600 to retain the old 14-day cookie behavior")

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
        report.info(f"{name}={raw} ({source}); this limit is enforced in 3.0")

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
    report.info("Healthy 3.0: /api/health returns 200 ok and /api/ready returns 200")
    report.info(
        "Invalid production config: /api/health returns 200 setup_required, "
        "/api/ready returns 503, and other routes remain unavailable"
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
