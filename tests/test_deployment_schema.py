import dataclasses
import json
from pathlib import Path

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


def test_schema_rejects_malformed_top_level_shape(tmp_path: Path) -> None:
    candidate = tmp_path / "schema.json"
    candidate.write_text("[]", encoding="utf-8")

    with pytest.raises(SchemaError, match="schema: must be an object"):
        load_schema(candidate)


def test_schema_rejects_secret_defaults(tmp_path: Path) -> None:
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    secret = next(setting for setting in raw["settings"] if setting["name"] == "SESSION_SECRET")
    secret["artifact_default"] = "SENTINEL_SESSION_SECRET"
    candidate = tmp_path / "schema.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaError, match="SESSION_SECRET: secret defaults must be empty"):
        load_schema(candidate)
