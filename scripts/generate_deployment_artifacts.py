"""Validate and generate appliance deployment artifacts from one schema."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "deploy" / "schema.json"

_TOP_LEVEL_FIELDS = (
    "schema_version",
    "application",
    "image",
    "process",
    "endpoints",
    "storage",
    "settings",
)
_SETTING_FIELDS = (
    "name",
    "description",
    "type",
    "runtime_default",
    "artifact_default",
    "required",
    "safe_example",
    "secret",
    "production",
    "restart_required",
    "proxy_relevance",
    "validation",
    "display",
    "preflight",
)


class SchemaError(ValueError):
    """Deployment schema is incomplete or malformed."""


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], path: str) -> None:
    for field in fields:
        if field not in value:
            raise SchemaError(f"{path}.{field}: is required")


def load_schema(path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    """Load and validate deployment metadata without exposing input values."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError("schema: could not be read as JSON") from exc
    if not isinstance(raw, dict):
        raise SchemaError("schema: must be an object")
    _require_fields(raw, _TOP_LEVEL_FIELDS, "schema")
    if raw["schema_version"] != 1:
        raise SchemaError("schema.schema_version: must equal 1")
    if not isinstance(raw["settings"], list):
        raise SchemaError("schema.settings: must be an array")

    names: set[str] = set()
    for index, setting in enumerate(raw["settings"]):
        path_name = f"settings[{index}]"
        if not isinstance(setting, dict):
            raise SchemaError(f"{path_name}: must be an object")
        _require_fields(setting, _SETTING_FIELDS, path_name)
        name = setting["name"]
        if not isinstance(name, str) or not name:
            raise SchemaError(f"{path_name}.name: must be a non-empty string")
        if name in names:
            raise SchemaError(f"settings: duplicate name {name}")
        names.add(name)
        if not isinstance(setting["secret"], bool):
            raise SchemaError(f"{path_name}.secret: must be a boolean")
        if setting["secret"] and setting["safe_example"] not in (None, ""):
            raise SchemaError(f"{path_name}.safe_example: secret examples must be empty")
    return raw


def _schema_hash(schema: dict[str, Any]) -> str:
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _environment(schema: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for setting in schema["settings"]:
        value = setting["artifact_default"]
        if isinstance(value, bool):
            values[setting["name"]] = "true" if value else "false"
        elif value is None:
            values[setting["name"]] = ""
        else:
            values[setting["name"]] = str(value)
    return values


def _compose_environment(schema: dict[str, Any]) -> dict[str, str]:
    return {name: f"${{{name}:-{value}}}" for name, value in _environment(schema).items()}


def _yaml_document(value: dict[str, Any], schema: dict[str, Any]) -> str:
    header = (
        "# Generated from deploy/schema.json; do not edit.\n"
        f"# Schema-Version: {schema['schema_version']}\n"
        f"# Schema-SHA256: {_schema_hash(schema)}\n"
    )
    return header + yaml.safe_dump(value, sort_keys=False, default_flow_style=False)


def _compose(schema: dict[str, Any]) -> str:
    image = schema["image"]
    model = {
        "services": {
            "emby-watchparty": {
                "image": f"{image['repository']}:{image['tag']}",
                "container_name": "emby-watchparty",
                "environment": _compose_environment(schema),
                "ports": ["5000:5000"],
                "volumes": [
                    "./data:/app/data",
                    "./images/avatars:/app/images/avatars",
                    "./logs:/app/logs",
                    "./config.json:/app/config.json",
                ],
                "restart": "unless-stopped",
            }
        }
    }
    preflight = (
        "# Preflight uses this service's environment and volumes:\n"
        "# docker compose -f docker-compose.yml.example run --rm --no-deps "
        "emby-watchparty python -m backend.migration_preflight "
        "--root /app --target production --deployment docker\n"
    )
    return preflight + _yaml_document(model, schema)


def _env_example(schema: dict[str, Any]) -> str:
    lines = [
        "# Generated from deploy/schema.json; do not edit.",
        f"# Schema-Version: {schema['schema_version']}",
        f"# Schema-SHA256: {_schema_hash(schema)}",
        "# Production starts fail-closed until every required blank is configured.",
        "",
    ]
    for setting in schema["settings"]:
        lines.append(f"# {setting['description']}")
        value = _environment({"settings": [setting]})[setting["name"]]
        lines.append(f"{setting['name']}={value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _environment_reference(schema: dict[str, Any]) -> str:
    lines = [
        "<!-- Generated from deploy/schema.json; do not edit. -->",
        f"<!-- Schema-Version: {schema['schema_version']} -->",
        f"<!-- Schema-SHA256: {_schema_hash(schema)} -->",
        "# Deployment environment",
        "",
        "Generated from `deploy/schema.json`. Every field requires container recreation.",
        "",
        "| Variable | Type | Required | Secret | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        (
            f"| `{setting['name']}` | {setting['type']} | {setting['required']} | "
            f"{'yes' if setting['secret'] else 'no'} | {setting['description']} |"
        )
        for setting in schema["settings"]
    )
    lines.extend(
        [
            "",
            "BEHIND_PROXY=true requires TRUSTED_PROXY_CIDRS; no universal CIDR is safe.",
            "Production requires explicit origins, secure cookies, and HLS token validation.",
            "Secret fields are intentionally blank. Generate and enter values outside tracked files.",
            "",
        ]
    )
    return "\n".join(lines)


def generate_artifacts(schema: dict[str, Any]) -> dict[Path, str]:
    """Render every deterministic artifact from validated schema data."""
    return {
        Path(".env.example"): _env_example(schema),
        Path("docker-compose.yml.example"): _compose(schema),
        Path("docs/deployment/environment.md"): _environment_reference(schema),
    }


def _write_artifacts(output_dir: Path, artifacts: dict[Path, str]) -> None:
    for relative, content in artifacts.items():
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")


def _check_artifacts(output_dir: Path, artifacts: dict[Path, str]) -> int:
    stale: list[Path] = []
    for relative, expected in artifacts.items():
        destination = output_dir / relative
        try:
            actual = destination.read_text(encoding="utf-8")
        except OSError:
            actual = ""
        if actual != expected:
            stale.append(relative)
    for relative in stale:
        print(f"stale deployment artifact: {relative}")
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    schema = load_schema(args.schema)
    artifacts = generate_artifacts(schema)
    if args.check:
        return _check_artifacts(args.output_dir, artifacts)
    _write_artifacts(args.output_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
