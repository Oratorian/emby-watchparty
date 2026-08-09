"""Validate and generate appliance deployment artifacts from one schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    load_schema(args.schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
