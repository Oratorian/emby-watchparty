import re
from pathlib import Path

import yaml

from scripts.generate_deployment_artifacts import generate_artifacts, load_schema, main

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_schema(ROOT / "deploy" / "schema.json")
SETTING_NAMES = [setting["name"] for setting in SCHEMA["settings"]]


def test_compose_uses_production_safe_schema_defaults() -> None:
    artifacts = generate_artifacts(SCHEMA)
    compose = yaml.safe_load(artifacts[Path("docker-compose.yml.example")])
    service = compose["services"]["emby-watchparty"]

    assert service["image"] == "ghcr.io/oratorian/emby-watchparty:3.0"
    assert list(service["environment"]) == SETTING_NAMES
    assert service["environment"]["WATCH_PARTY_BIND"] == "0.0.0.0"
    assert service["environment"]["WATCH_PARTY_PORT"] == "5000"
    assert service["ports"] == ["5000:5000"]
    assert service["environment"]["APP_ENV"] == "${APP_ENV:-production}"
    assert service["environment"]["SESSION_COOKIE_SECURE"] == ("${SESSION_COOKIE_SECURE:-true}")
    assert service["environment"]["ENABLE_HLS_TOKEN_VALIDATION"] == (
        "${ENABLE_HLS_TOKEN_VALIDATION:-true}"  # noqa: S105 -- configuration boolean
    )
    assert service["environment"]["BEHIND_PROXY"] == "${BEHIND_PROXY:-}"
    assert service["environment"]["TRUSTED_PROXY_CIDRS"] == "${TRUSTED_PROXY_CIDRS:-}"
    assert "WEB_CONCURRENCY" not in service["environment"]
    assert len(compose["services"]) == 1


def test_generated_examples_never_contain_secret_values() -> None:
    artifacts = generate_artifacts(SCHEMA)
    combined = "\n".join(artifacts.values())

    assert "SENTINEL_SESSION_SECRET" not in combined
    assert "SENTINEL_EMBY_API_KEY" not in combined
    assert re.search(r"^SESSION_SECRET=$", artifacts[Path(".env.example")], re.MULTILINE)
    assert re.search(r"^EMBY_API_KEY=$", artifacts[Path(".env.example")], re.MULTILINE)


def test_generation_is_byte_deterministic() -> None:
    assert generate_artifacts(SCHEMA) == generate_artifacts(SCHEMA)


def test_environment_reference_carries_schema_metadata() -> None:
    reference = generate_artifacts(SCHEMA)[Path("docs/deployment/environment.md")]

    assert "Generated from `deploy/schema.json`" in reference
    assert "| `SESSION_SECRET` | string | production | yes |" in reference
    assert "BEHIND_PROXY=true requires TRUSTED_PROXY_CIDRS" in reference


def test_unraid_is_owned_outside_the_canonical_artifact_set() -> None:
    artifacts = generate_artifacts(SCHEMA)

    assert Path("deploy/unraid/emby-watchparty.xml") not in artifacts


def test_casaos_manifest_is_compose_with_current_top_level_metadata() -> None:
    manifest = generate_artifacts(SCHEMA)[Path("deploy/casaos/docker-compose.yml")]
    model = yaml.safe_load(manifest)
    service = model["services"]["emby-watchparty"]
    metadata = model["x-casaos"]

    assert model["name"] == "emby-watchparty"
    assert list(service["environment"]) == SETTING_NAMES
    assert service["environment"]["EMBY_API_KEY"] == ""
    assert service["environment"]["SESSION_SECRET"] == ""
    assert metadata["id"] == "com.oratorian.emby-watchparty"
    assert metadata["main"] == "emby-watchparty"
    assert metadata["port_map"] == "5000"
    assert service["ports"] == [{"target": 5000, "published": "5000", "protocol": "tcp"}]
    assert metadata["architectures"] == ["amd64", "arm64"]
    assert "Schema-SHA256:" in manifest


def test_truenas_custom_app_uses_host_paths_without_privilege() -> None:
    manifest = generate_artifacts(SCHEMA)[Path("deploy/truenas/custom-app.yml")]
    model = yaml.safe_load(manifest)
    service = model["services"]["emby-watchparty"]

    assert list(service["environment"]) == SETTING_NAMES
    assert service["environment"]["EMBY_API_KEY"] == ""
    assert service["environment"]["SESSION_SECRET"] == ""
    assert service["ports"] == ["5000:5000"]
    assert all(volume.startswith("/mnt/") for volume in service["volumes"])
    assert "privileged" not in service
    assert "cap_add" not in service
    assert "WEB_CONCURRENCY" not in manifest
    assert "Schema-SHA256:" in manifest


def test_all_platforms_share_vocabulary_and_schema_hash() -> None:
    artifacts = generate_artifacts(SCHEMA)
    compose = yaml.safe_load(artifacts[Path("docker-compose.yml.example")])
    casaos = yaml.safe_load(artifacts[Path("deploy/casaos/docker-compose.yml")])
    truenas = yaml.safe_load(artifacts[Path("deploy/truenas/custom-app.yml")])
    vocabularies = [
        list(compose["services"]["emby-watchparty"]["environment"]),
        list(casaos["services"]["emby-watchparty"]["environment"]),
        list(truenas["services"]["emby-watchparty"]["environment"]),
    ]
    hashes = {
        match.group(1)
        for content in artifacts.values()
        if (match := re.search(r"Schema-SHA256:\s*([0-9a-f]{64})", content))
    }

    assert vocabularies == [SETTING_NAMES] * 3
    assert len(hashes) == 1
    assert len(artifacts) == 5


def test_appliance_wrappers_preserve_the_canonical_compose_service() -> None:
    artifacts = generate_artifacts(SCHEMA)
    models = [
        yaml.safe_load(artifacts[path])
        for path in (
            Path("docker-compose.yml.example"),
            Path("deploy/casaos/docker-compose.yml"),
            Path("deploy/truenas/custom-app.yml"),
        )
    ]
    services = [model["services"]["emby-watchparty"] for model in models]
    canonical = services[0]

    assert all(service["image"] == canonical["image"] for service in services)
    assert all(service["container_name"] == canonical["container_name"] for service in services)
    assert all(service["restart"] == canonical["restart"] for service in services)
    assert all(list(service["environment"]) == SETTING_NAMES for service in services)
    assert all(
        [volume.rsplit(":", 1)[1] for volume in service["volumes"]]
        == [volume.rsplit(":", 1)[1] for volume in canonical["volumes"]]
        for service in services
    )


def test_check_mode_detects_missing_and_changed_artifacts(tmp_path: Path, capsys) -> None:
    assert main(["--output-dir", str(tmp_path)]) == 0
    assert main(["--output-dir", str(tmp_path), "--check"]) == 0

    changed = tmp_path / "docker-compose.yml.example"
    changed.write_text("changed", encoding="utf-8")
    missing = tmp_path / "deploy" / "casaos" / "docker-compose.yml"
    missing.unlink()

    assert main(["--output-dir", str(tmp_path), "--check"]) == 1
    output = capsys.readouterr().out
    assert "docker-compose.yml.example" in output
    assert "deploy/casaos/docker-compose.yml" in output
