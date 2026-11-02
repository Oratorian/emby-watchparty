import tomllib
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement


@pytest.mark.parametrize("lockfile", ["requirements.txt", "requirements-dev.txt"])
@pytest.mark.parametrize(
    ("sys_platform", "implementation", "uvloop_supported"),
    [
        pytest.param("win32", "CPython", False, id="windows"),
        pytest.param("linux", "CPython", True, id="linux"),
        pytest.param("darwin", "CPython", True, id="macos"),
        pytest.param("cygwin", "CPython", False, id="cygwin"),
        pytest.param("linux", "PyPy", False, id="pypy"),
    ],
)
def test_dependency_locks_select_supported_platform_packages(
    lockfile: str, sys_platform: str, implementation: str, uvloop_supported: bool
) -> None:
    project_root = Path(__file__).parent.parent
    lock = (project_root / lockfile).read_text(encoding="utf-8")
    requirements = [
        Requirement(line.removesuffix("\\").strip())
        for line in lock.splitlines()
        if line and not line[0].isspace() and not line.startswith("#")
    ]
    environment = default_environment()
    environment.update(sys_platform=sys_platform, platform_python_implementation=implementation)
    selected = {
        requirement.name
        for requirement in requirements
        if requirement.marker is None or requirement.marker.evaluate(environment)
    }

    assert ("uvloop" in selected) is uvloop_supported
    assert ("colorama" in selected) is (sys_platform == "win32")
    if lockfile == "requirements-dev.txt":
        assert ("librt" in selected) is (implementation != "PyPy")


def test_development_lock_contains_uvicorn_standard_extras() -> None:
    project_root = Path(__file__).parent.parent
    lock = (project_root / "requirements-dev.txt").read_text(encoding="utf-8")

    for package in ("httptools", "uvloop", "watchfiles", "websockets"):
        assert f"{package}==" in lock


def test_project_rejects_unsupported_python_versions() -> None:
    project_root = Path(__file__).parent.parent
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["project"]["requires-python"] == ">=3.12,<3.13"
