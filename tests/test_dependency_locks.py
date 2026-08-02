from pathlib import Path


def test_development_lock_contains_uvicorn_standard_extras() -> None:
    project_root = Path(__file__).parent.parent
    lock = (project_root / "requirements-dev.txt").read_text(encoding="utf-8")

    for package in ("httptools", "uvloop", "watchfiles", "websockets"):
        assert f"{package}==" in lock
