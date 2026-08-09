import copy
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.src.config import Config, EnvConfig, RuntimeConfig
from scripts.generate_deployment_artifacts import (
    SchemaError,
    generate_artifacts,
    load_schema,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "deploy" / "schema.json"
SCHEMA = load_schema(SCHEMA_PATH)


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


def test_omitted_settings_ship_absent_and_commented_not_blank() -> None:
    """A blank value is *declared*, which is the opposite of what these mean.

    `EnvConfig.declared()` is a membership test, so `BEHIND_PROXY=` is parsed
    and fails with "Must be true or false" in every environment, replacing the
    tri-state guidance with a parse error and refusing the boot. Absent is the
    only encoding of "the operator has not chosen yet".
    """
    artifacts = generate_artifacts(SCHEMA)
    omitted = [s["name"] for s in SCHEMA["settings"] if s["artifact_omit"]]
    assert omitted, "the omit mechanism is unused; this test would be vacuous"

    env_example = artifacts[Path(".env.example")]
    for name in omitted:
        assert f"\n# {name}=" in env_example
        assert f"\n{name}=" not in env_example

    for path in (
        Path("docker-compose.yml.example"),
        Path("deploy/casaos/docker-compose.yml"),
        Path("deploy/truenas/custom-app.yml"),
    ):
        document = artifacts[path]
        service = yaml.safe_load(document)["services"]["emby-watchparty"]
        for name in omitted:
            assert name not in service["environment"]
            # Present as guidance so an operator can still find and set it.
            assert f"# {name}: " in document


def test_a_deployment_built_from_the_env_example_actually_boots() -> None:
    """The artifacts are only useful if what they generate can start.

    Every appliance path and the documented contributor setup begin by copying
    `.env.example`. Shipping one that cannot boot made all four dead on arrival
    while every drift test stayed green, because nothing here ever asked the
    real loader what it made of the output.
    """
    import os
    import tempfile

    artifacts = generate_artifacts(SCHEMA)
    root = Path(tempfile.mkdtemp())
    (root / ".env").write_text(
        artifacts[Path(".env.example")] + "\nAPP_ENV=development\n", encoding="utf-8"
    )

    saved = dict(os.environ)
    os.environ.clear()
    try:
        errors: dict[str, str] = {}
        env = EnvConfig.from_env(root, errors=errors)
        assert Config(env, RuntimeConfig(), load_errors=errors).startup_errors() == {}
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_committed_env_example_boots_through_the_real_loader(tmp_path: Path) -> None:
    """The checked-in operator artifact must preserve intentional absence."""
    import os

    (tmp_path / ".env").write_text(
        (ROOT / ".env.example").read_text(encoding="utf-8") + "\nAPP_ENV=development\n",
        encoding="utf-8",
    )

    saved = dict(os.environ)
    os.environ.clear()
    try:
        errors: dict[str, str] = {}
        env = EnvConfig.from_env(tmp_path, errors=errors)
        assert env.BEHIND_PROXY is None
        assert env.SESSION_COOKIE_SECURE is False
        assert Config(env, RuntimeConfig(), load_errors=errors).startup_errors() == {}
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_validation_patterns_agree_with_the_loader_they_describe() -> None:
    """The schema is a third description of config.py's rules; pin them together.

    A published pattern looser than the boot gate sends an operator to a value
    the server then refuses, with an error message that contradicts the docs
    they just read.
    """
    from backend.src.config import _APP_PREFIX_RE

    pattern = next(
        s["validation"]["pattern"] for s in SCHEMA["settings"] if s["name"] == "APP_PREFIX"
    )
    compiled = re.compile(pattern)

    accepted_by_boot_gate = ["/watchparty", "/a/b", "/x.y_z~w-v"]
    refused_by_boot_gate = ["/_media", "/-wp", "/.hidden", "/~user", "no-slash", "/"]

    for value in accepted_by_boot_gate:
        assert _APP_PREFIX_RE.fullmatch(value), value
        assert compiled.fullmatch(value), f"schema rejects what the loader accepts: {value}"
    for value in refused_by_boot_gate:
        assert not _APP_PREFIX_RE.fullmatch(value), value
        assert not compiled.fullmatch(value), f"schema admits what the loader refuses: {value}"


def test_storage_drives_the_generated_volume_mounts() -> None:
    """schema.storage must reach the artifacts, not just the validator.

    It was decoration: the mount list was a literal in the generator, so adding
    a required mount to the schema changed the hash, satisfied --check and the
    drift tests, and produced no volume anywhere. The schema described one
    deployment while the artifacts shipped another.
    """
    targets = {item["target"] for item in SCHEMA["storage"]}
    for path in (
        Path("docker-compose.yml.example"),
        Path("deploy/casaos/docker-compose.yml"),
        Path("deploy/truenas/custom-app.yml"),
    ):
        service = yaml.safe_load(generate_artifacts(SCHEMA)[path])["services"]["emby-watchparty"]
        # rsplit: appliance host paths are ${VAR:-default}, so the first colon
        # belongs to the interpolation, not the mount separator.
        mounted = {entry.rsplit(":", 1)[1] for entry in service["volumes"]}
        assert mounted == targets, path

    extended = copy.deepcopy(SCHEMA)
    extended["storage"].append(
        {
            "id": "cache",
            "target": "/app/cache",
            "kind": "directory",
            "required": True,
            "writable": True,
        }
    )
    extended_artifacts = generate_artifacts(extended)
    for path in (
        Path("docker-compose.yml.example"),
        Path("deploy/casaos/docker-compose.yml"),
        Path("deploy/truenas/custom-app.yml"),
    ):
        service = yaml.safe_load(extended_artifacts[path])["services"]["emby-watchparty"]
        mounted = {entry.rsplit(":", 1)[1] for entry in service["volumes"]}
        assert "/app/cache" in mounted, path
