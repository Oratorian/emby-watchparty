import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from scripts.generate_deployment_artifacts import generate_artifacts, load_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_schema(ROOT / "deploy" / "schema.json")
SETTING_NAMES = [setting["name"] for setting in SCHEMA["settings"]]


def test_compose_uses_production_safe_schema_defaults() -> None:
    artifacts = generate_artifacts(SCHEMA)
    compose = yaml.safe_load(artifacts[Path("docker-compose.yml.example")])
    service = compose["services"]["emby-watchparty"]

    assert service["image"] == "ghcr.io/oratorian/emby-watchparty:3.0"
    assert list(service["environment"]) == SETTING_NAMES
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


def test_unraid_template_exposes_schema_fields_and_persistent_paths() -> None:
    artifacts = generate_artifacts(SCHEMA)
    xml = artifacts[Path("deploy/unraid/emby-watchparty.xml")]
    root = ET.fromstring(xml)  # noqa: S314 -- parser input is this generator's output
    configs = root.findall("Config")
    variables = [item for item in configs if item.attrib["Type"] == "Variable"]
    paths = [item.attrib["Target"] for item in configs if item.attrib["Type"] == "Path"]

    assert [item.attrib["Target"] for item in variables] == SETTING_NAMES
    assert {item.attrib["Target"] for item in variables if item.attrib["Mask"] == "true"} == {
        "EMBY_API_KEY",
        "SESSION_SECRET",
    }
    assert paths == ["/app/data", "/app/images/avatars", "/app/logs", "/app/config.json"]
    assert root.findtext("Repository") == "ghcr.io/oratorian/emby-watchparty:3.0"
    assert "WEB_CONCURRENCY" not in xml
    assert "Schema-SHA256:" in xml
