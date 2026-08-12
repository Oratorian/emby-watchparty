"""The development compose file must actually start the application.

Compose expands an unset variable to an empty string, not to "absent", and the
config parser treats an empty SESSION_COOKIE_SECURE or BEHIND_PROXY as invalid
rather than as unset. A compose file that relies on the caller having exported
everything therefore cannot boot from a bare checkout, which is the one case
it exists to serve.
"""

import re
from pathlib import Path

import pytest
import yaml

from backend.src.config import EnvConfig

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.dev.yml"
# The only two a developer genuinely has to supply.
REQUIRED = {"EMBY_SERVER_URL": "http://emby.example:8096", "EMBY_API_KEY": "test-key"}


def _environment() -> dict[str, str]:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return document["services"]["emby-watchparty"]["environment"]


def _expand(value: object, provided: dict[str, str]) -> str:
    """Resolve ${VAR}, ${VAR:-default} and ${VAR:?message} as Compose does."""
    text = str(value)
    required = re.fullmatch(r"\$\{([A-Z_]+):\?[^}]*\}", text)
    if required:
        return provided[required.group(1)]
    defaulted = re.fullmatch(r"\$\{([A-Z_]+):-([^}]*)\}", text)
    if defaulted:
        return provided.get(defaulted.group(1), defaulted.group(2))
    bare = re.fullmatch(r"\$\{([A-Z_]+)\}", text)
    if bare:
        return provided.get(bare.group(1), "")
    return text


def test_dev_compose_boots_with_nothing_but_the_emby_credentials() -> None:
    errors: dict[str, str] = {}
    environment = {key: _expand(value, REQUIRED) for key, value in _environment().items()}

    config = EnvConfig.from_env(environ=environment, errors=errors)

    assert errors == {}, f"development compose cannot boot: {errors}"
    assert config.APP_ENV in {"development", "production"}


def test_every_dev_compose_variable_declares_a_default_or_is_marked_required() -> None:
    """A bare ${VAR} is the shape that produced the unbootable config.

    It looks like "inherit from the environment" and behaves like "set this to
    empty string", which the parser then rejects with no indication that the
    compose file caused it.
    """
    bare = [
        key for key, value in _environment().items() if re.fullmatch(r"\$\{[A-Z_]+\}", str(value))
    ]

    assert not bare, f"variables that expand to an empty string when unset: {bare}"


def test_the_dev_compose_does_not_occupy_the_operators_filename() -> None:
    """docker-compose.yml is Compose's default and the name the docs tell
    operators to create by copying the generated example. A checked-in file
    there shadows both."""
    assert not (ROOT / "docker-compose.yml").exists()
    assert COMPOSE.exists()
    assert (ROOT / "docker-compose.yml.example").exists()


@pytest.mark.parametrize("key", ["SESSION_COOKIE_SECURE", "BEHIND_PROXY", "APP_ENV"])
def test_the_values_that_previously_broke_the_boot_are_still_defaulted(key: str) -> None:
    assert not re.fullmatch(r"\$\{[A-Z_]+\}", str(_environment()[key]))
