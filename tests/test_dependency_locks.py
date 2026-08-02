import tomllib
from pathlib import Path


def test_development_lock_contains_uvicorn_standard_extras() -> None:
    project_root = Path(__file__).parent.parent
    lock = (project_root / "requirements-dev.txt").read_text(encoding="utf-8")

    for package in ("httptools", "uvloop", "watchfiles", "websockets"):
        assert f"{package}==" in lock


def test_project_rejects_unsupported_python_versions() -> None:
    project_root = Path(__file__).parent.parent
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["project"]["requires-python"] == ">=3.12,<3.13"
