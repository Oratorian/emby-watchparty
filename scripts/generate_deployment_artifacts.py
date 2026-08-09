"""Validate and generate appliance deployment artifacts from one schema."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]  # PyYAML ships no inline type information.

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
_APPLICATION_FIELDS = ("id", "name", "configuration_mode", "container_port")
_IMAGE_FIELDS = ("repository", "tag", "platforms")
_ENDPOINT_FIELDS = ("health", "readiness")
_STORAGE_FIELDS = ("id", "target", "kind", "required", "writable")
_DISPLAY_FIELDS = ("label", "group", "order", "advanced")
_PREFLIGHT_FIELDS = ("relevant", "legacy_source")
_SETTING_TYPES = {
    "boolean",
    "csv_cidr",
    "csv_http_origins",
    "enum",
    "http_url",
    "integer",
    "path_prefix",
    "string",
}
_REQUIRED_MODES = {"always", "optional", "production", "when_proxy"}


class SchemaError(ValueError):
    """Deployment schema is incomplete or malformed."""


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], path: str) -> None:
    for field in fields:
        if field not in value:
            raise SchemaError(f"{path}.{field}: is required")


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{path}: must be an object")
    return value


def _require_array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaError(f"{path}: must be an array")
    return value


def _require_value_type(value: Any, expected: type[Any], label: str, path: str) -> None:
    if type(value) is not expected:
        raise SchemaError(f"{path}: must be {label}")


def _require_string(value: Any, path: str) -> None:
    _require_value_type(value, str, "a string", path)


def _require_integer(value: Any, path: str) -> None:
    _require_value_type(value, int, "an integer", path)


def _require_boolean(value: Any, path: str) -> None:
    _require_value_type(value, bool, "a boolean", path)


def _require_string_array(value: Any, path: str) -> None:
    values = _require_array(value, path)
    for index, item in enumerate(values):
        _require_string(item, f"{path}[{index}]")


def _validate_rule_types(rules: dict[str, Any], path: str) -> None:
    integer_rules = {
        "maximum",
        "maximum_length",
        "minimum",
        "minimum_length",
        "minimum_length_in_production",
    }
    string_rules = {"format", "items", "pattern"}
    string_array_rules = {"allowed_strings", "item_schemes", "schemes"}
    for name, value in rules.items():
        rule_path = f"{path}.{name}"
        if name in integer_rules:
            _require_integer(value, rule_path)
        elif name in string_rules:
            _require_string(value, rule_path)
        elif name in string_array_rules:
            _require_string_array(value, rule_path)
        elif name == "allowed":
            _require_array(value, rule_path)
        else:
            raise SchemaError(f"{rule_path}: is not supported")


def _validate_production(production: dict[str, Any], path: str) -> None:
    for name, value in production.items():
        rule_path = f"{path}.{name}"
        if name == "required":
            _require_boolean(value, rule_path)
        elif name == "minimum_length":
            _require_integer(value, rule_path)
        elif name == "forbidden_values":
            _require_array(value, rule_path)
        elif name == "required_when":
            condition = _require_object(value, rule_path)
            _require_fields(condition, ("field", "equals"), rule_path)
            _require_string(condition["field"], f"{rule_path}.field")
        elif name != "required_value":
            raise SchemaError(f"{rule_path}: is not supported")


def _validate_setting_value(
    value: Any, setting_type: str, path: str, *, allow_blank: bool = False
) -> None:
    if value is None or (allow_blank and value == ""):
        return
    if setting_type == "integer":
        _require_integer(value, path)
    elif setting_type == "boolean":
        _require_boolean(value, path)
    else:
        _require_string(value, path)


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
    application = _require_object(raw["application"], "schema.application")
    _require_fields(application, _APPLICATION_FIELDS, "schema.application")
    for field in ("id", "name", "configuration_mode"):
        _require_string(application[field], f"schema.application.{field}")
    _require_integer(application["container_port"], "schema.application.container_port")
    if application["container_port"] != 5000:
        raise SchemaError("schema.application.container_port: must equal 5000")
    image = _require_object(raw["image"], "schema.image")
    _require_fields(image, _IMAGE_FIELDS, "schema.image")
    _require_string(image["repository"], "schema.image.repository")
    _require_string(image["tag"], "schema.image.tag")
    _require_string_array(image["platforms"], "schema.image.platforms")
    process = _require_object(raw["process"], "schema.process")
    _require_fields(process, ("workers",), "schema.process")
    if process["workers"] != 1:
        raise SchemaError("schema.process.workers: must equal 1")
    endpoints = _require_object(raw["endpoints"], "schema.endpoints")
    _require_fields(endpoints, _ENDPOINT_FIELDS, "schema.endpoints")
    for field in _ENDPOINT_FIELDS:
        _require_string(endpoints[field], f"schema.endpoints.{field}")
    storage_items = _require_array(raw["storage"], "schema.storage")
    for index, storage in enumerate(storage_items):
        storage_path = f"schema.storage[{index}]"
        storage = _require_object(storage, storage_path)
        _require_fields(storage, _STORAGE_FIELDS, storage_path)
        for field in ("id", "target", "kind"):
            _require_string(storage[field], f"{storage_path}.{field}")
        for field in ("required", "writable"):
            _require_boolean(storage[field], f"{storage_path}.{field}")
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
        for field in ("description", "type", "required", "proxy_relevance"):
            _require_string(setting[field], f"{path_name}.{field}")
        setting_type = setting["type"]
        if setting_type not in _SETTING_TYPES:
            raise SchemaError(f"{path_name}.type: is not supported")
        if setting["required"] not in _REQUIRED_MODES:
            raise SchemaError(f"{path_name}.required: is not supported")
        for field in ("runtime_default", "artifact_default", "safe_example"):
            _validate_setting_value(
                setting[field],
                setting_type,
                f"{path_name}.{field}",
                allow_blank=field == "artifact_default",
            )
        for field in ("secret", "restart_required"):
            _require_boolean(setting[field], f"{path_name}.{field}")
        validation = _require_object(setting["validation"], f"{path_name}.validation")
        _validate_rule_types(validation, f"{path_name}.validation")
        display = _require_object(setting["display"], f"{path_name}.display")
        _require_fields(display, _DISPLAY_FIELDS, f"{path_name}.display")
        for field in ("label", "group"):
            _require_string(display[field], f"{path_name}.display.{field}")
        _require_integer(display["order"], f"{path_name}.display.order")
        _require_boolean(display["advanced"], f"{path_name}.display.advanced")
        production = _require_object(setting["production"], f"{path_name}.production")
        _validate_production(production, f"{path_name}.production")
        preflight = _require_object(setting["preflight"], f"{path_name}.preflight")
        _require_fields(preflight, _PREFLIGHT_FIELDS, f"{path_name}.preflight")
        _require_boolean(preflight["relevant"], f"{path_name}.preflight.relevant")
        legacy_source = preflight["legacy_source"]
        if legacy_source is not None:
            _require_string(legacy_source, f"{path_name}.preflight.legacy_source")
        if setting["secret"] and setting["safe_example"] not in (None, ""):
            raise SchemaError(f"{path_name}.safe_example: secret examples must be empty")
        if setting["secret"] and (
            setting["runtime_default"] not in (None, "")
            or setting["artifact_default"] not in (None, "")
        ):
            raise SchemaError(f"{name}: secret defaults must be empty")
    settings_by_name = {setting["name"]: setting for setting in raw["settings"]}
    for required_name in ("WATCH_PARTY_BIND", "WATCH_PARTY_PORT"):
        if required_name not in settings_by_name:
            raise SchemaError(f"settings: {required_name} is required")
    if settings_by_name["WATCH_PARTY_BIND"]["artifact_default"] != "0.0.0.0":  # noqa: S104 -- containers must accept published-port traffic.
        raise SchemaError("WATCH_PARTY_BIND.artifact_default: must equal 0.0.0.0")
    if settings_by_name["WATCH_PARTY_PORT"]["artifact_default"] != 5000:
        raise SchemaError("WATCH_PARTY_PORT.artifact_default: must equal 5000")
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


def _compose_model(schema: dict[str, Any]) -> dict[str, Any]:
    image = schema["image"]
    container_port = schema["application"]["container_port"]
    environment = _compose_environment(schema)
    artifact_environment = _environment(schema)
    environment["WATCH_PARTY_BIND"] = artifact_environment["WATCH_PARTY_BIND"]
    environment["WATCH_PARTY_PORT"] = str(container_port)
    return {
        "services": {
            "emby-watchparty": {
                "image": f"{image['repository']}:{image['tag']}",
                "container_name": "emby-watchparty",
                "environment": environment,
                "ports": [f"{container_port}:{container_port}"],
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


def _compose(schema: dict[str, Any]) -> str:
    preflight = (
        "# Preflight uses this service's environment and volumes:\n"
        "# docker compose -f docker-compose.yml.example run --rm --no-deps "
        "emby-watchparty python -m backend.migration_preflight "
        "--root /app --target production --deployment docker\n"
    )
    return preflight + _yaml_document(_compose_model(schema), schema)


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


def _appliance_compose_model(schema: dict[str, Any], data_root: str) -> dict[str, Any]:
    model = copy.deepcopy(_compose_model(schema))
    service = model["services"]["emby-watchparty"]
    service["environment"] = _environment(schema)
    service["volumes"] = [
        f"{data_root}/{volume.split(':', 1)[0].removeprefix('./')}:{volume.rsplit(':', 1)[1]}"
        for volume in service["volumes"]
    ]
    return {"name": "emby-watchparty", **model}


def _casaos(schema: dict[str, Any]) -> str:
    model = _appliance_compose_model(schema, "${APP_DATA_DIR:-/DATA/AppData/emby-watchparty}")
    container_port = schema["application"]["container_port"]
    service = model["services"]["emby-watchparty"]
    service["ports"] = [
        {"target": container_port, "published": str(container_port), "protocol": "tcp"}
    ]
    model["x-casaos"] = {
        "id": "com.oratorian.emby-watchparty",
        "main": "emby-watchparty",
        "index": "/",
        "port_map": str(container_port),
        "scheme": "http",
        "icon": "https://raw.githubusercontent.com/Oratorian/emby-watchparty/3.0-dev/frontend/public/favicon.ico",
        "title": {"en_US": "Emby Watch Party"},
        "tagline": {"en_US": "Synchronized Emby playback for remote parties"},
        "description": {
            "en_US": "Host synchronized watch parties backed by an existing Emby server."
        },
        "author": "Oratorian",
        "developer": "Oratorian",
        "category": "Media",
        "architectures": ["amd64", "arm64"],
        "version": "3.0",
        "repo": "https://github.com/Oratorian/emby-watchparty",
        "support": "https://github.com/Oratorian/emby-watchparty/issues",
    }
    return _yaml_document(model, schema)


def _truenas(schema: dict[str, Any]) -> str:
    model = _appliance_compose_model(schema, "/mnt/POOL/emby-watchparty")
    warning = "# TrueNAS SCALE 24.10+ Custom App YAML. Replace POOL before deployment.\n"
    return warning + _yaml_document(model, schema)


def generate_artifacts(schema: dict[str, Any]) -> dict[Path, str]:
    """Render every deterministic artifact from validated schema data."""
    return {
        Path(".env.example"): _env_example(schema),
        Path("docker-compose.yml.example"): _compose(schema),
        Path("docs/deployment/environment.md"): _environment_reference(schema),
        Path("deploy/casaos/docker-compose.yml"): _casaos(schema),
        Path("deploy/truenas/custom-app.yml"): _truenas(schema),
    }


def _write_artifacts(output_dir: Path, artifacts: dict[Path, str]) -> None:
    for relative, content in artifacts.items():
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")


def _marked_artifact_paths(output_dir: Path) -> set[Path]:
    candidates: set[Path] = set()
    if output_dir.is_dir():
        candidates.update(path for path in output_dir.iterdir() if path.is_file())
    for owned_root in (output_dir / "deploy", output_dir / "docs" / "deployment"):
        if owned_root.is_dir():
            candidates.update(path for path in owned_root.rglob("*") if path.is_file())

    marked: set[Path] = set()
    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "Schema-SHA256:" in content:
            marked.add(candidate.relative_to(output_dir))
    return marked


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
        print(f"stale deployment artifact: {relative.as_posix()}")
    extra = sorted(_marked_artifact_paths(output_dir) - artifacts.keys())
    for relative in extra:
        print(f"extra deployment artifact: {relative.as_posix()}")
    return 1 if stale or extra else 0


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
