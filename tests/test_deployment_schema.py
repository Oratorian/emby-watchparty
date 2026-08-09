import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from backend.src.config import EnvConfig
from scripts.generate_deployment_artifacts import SchemaError, load_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "deploy" / "schema.json"


def test_canonical_schema_describes_every_deployment_environment_variable() -> None:
    schema = load_schema(SCHEMA_PATH)

    names = [setting["name"] for setting in schema["settings"]]
    env_fields = [field.name for field in dataclasses.fields(EnvConfig)]

    assert names == env_fields
    assert schema["process"] == {"workers": 1}
    assert schema["image"]["platforms"] == ["linux/amd64", "linux/arm64"]


def test_schema_rejects_missing_setting_metadata(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    del raw["settings"][0]["secret"]
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=r"settings\[0\]\.secret: is required"):
        load_schema(candidate)


def test_schema_rejects_duplicate_setting_names(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["settings"].append(dict(raw["settings"][0]))
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match="settings: duplicate name WATCH_PARTY_BIND"):
        load_schema(candidate)


def test_schema_rejects_missing_container_setting_without_internal_error(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["settings"] = [
        setting for setting in raw["settings"] if setting["name"] != "WATCH_PARTY_BIND"
    ]
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match="settings: WATCH_PARTY_BIND is required"):
        load_schema(candidate)


def test_schema_rejects_malformed_top_level_shape(tmp_path: Path) -> None:
    candidate = tmp_path / "schema.json"
    candidate.write_text("[]", encoding="utf-8")

    with pytest.raises(SchemaError, match="schema: must be an object"):
        load_schema(candidate)


def test_schema_rejects_malformed_application_metadata(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["application"] = "not-an-object"
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=r"schema\.application: must be an object"):
        load_schema(candidate)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("application", "container_port"), 5001, "schema.application.container_port"),
        (("process", "workers"), 2, "schema.process.workers"),
        (("settings", 0, "artifact_default"), "127.0.0.1", "WATCH_PARTY_BIND"),
        (("settings", 1, "artifact_default"), 5001, "WATCH_PARTY_PORT"),
    ],
)
def test_schema_rejects_noncanonical_container_invariants(
    tmp_path: Path, path: tuple[str | int, ...], value: object, message: str
) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=message):
        load_schema(candidate)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("image",), [], "schema.image: must be an object"),
        (("process",), [], "schema.process: must be an object"),
        (("endpoints",), [], "schema.endpoints: must be an object"),
        (("storage",), {}, "schema.storage: must be an array"),
        (("settings", 0, "validation"), [], r"settings\[0\]\.validation: must be an object"),
        (("settings", 0, "display"), [], r"settings\[0\]\.display: must be an object"),
        (("settings", 0, "production"), [], r"settings\[0\]\.production: must be an object"),
        (("settings", 0, "preflight"), [], r"settings\[0\]\.preflight: must be an object"),
    ],
)
def test_schema_rejects_malformed_nested_metadata(
    tmp_path: Path, path: tuple[str | int, ...], value: object, message: str
) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=message):
        load_schema(candidate)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("application", "id"), 1, "schema.application.id: must be a string"),
        (("image", "platforms"), "amd64", "schema.image.platforms: must be an array"),
        (("endpoints", "health"), 200, "schema.endpoints.health: must be a string"),
        (("storage", 0, "required"), "yes", r"schema.storage\[0\]\.required: must be a boolean"),
        (("settings", 0, "description"), [], r"settings\[0\]\.description: must be a string"),
        (
            ("settings", 0, "restart_required"),
            "yes",
            r"settings\[0\]\.restart_required: must be a boolean",
        ),
        (
            ("settings", 0, "validation", "format"),
            [],
            r"settings\[0\]\.validation.format: must be a string",
        ),
        (
            ("settings", 0, "display", "advanced"),
            "no",
            r"settings\[0\]\.display.advanced: must be a boolean",
        ),
        (
            ("settings", 0, "production", "required"),
            "yes",
            r"settings\[0\]\.production.required: must be a boolean",
        ),
        (
            ("settings", 0, "preflight", "relevant"),
            "yes",
            r"settings\[0\]\.preflight.relevant: must be a boolean",
        ),
    ],
)
def test_schema_rejects_malformed_metadata_values(
    tmp_path: Path, path: tuple[str | int, ...], value: object, message: str
) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=message):
        load_schema(candidate)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("settings", 3, "artifact_default"),
            "86400",
            r"settings\[3\]\.artifact_default: must be an integer",
        ),
        (
            ("settings", 8, "safe_example"),
            "true",
            r"settings\[8\]\.safe_example: must be a boolean",
        ),
        (("settings", 0, "type"), "mystery", r"settings\[0\]\.type: is not supported"),
        (("settings", 0, "required"), "sometimes", r"settings\[0\]\.required: is not supported"),
    ],
)
def test_schema_rejects_setting_values_that_disagree_with_parser_metadata(
    tmp_path: Path, path: tuple[str | int, ...], value: object, message: str
) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match=message):
        load_schema(candidate)


def test_schema_rejects_secret_defaults(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    secret = next(setting for setting in raw["settings"] if setting["name"] == "SESSION_SECRET")
    secret["artifact_default"] = "SENTINEL_SESSION_SECRET"
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match="SESSION_SECRET: secret defaults must be empty"):
        load_schema(candidate)
