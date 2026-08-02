import json
import os
from pathlib import Path

import pytest

from backend.src.bootstrap import SetupAttemptLimiter, save_bootstrap_config
from backend.src.config import Config


def test_boot_config_source_precedence_does_not_mutate_environment(
    tmp_path: Path, monkeypatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "bootstrap.json").write_text(
        json.dumps({"EMBY_API_KEY": "persisted-key"}), encoding="utf-8"
    )
    (tmp_path / ".env").write_text("EMBY_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.delenv("EMBY_API_KEY", raising=False)

    dotenv_config = Config.from_env(tmp_path)

    assert dotenv_config.EMBY_API_KEY == "dotenv-key"
    assert "EMBY_API_KEY" not in os.environ

    monkeypatch.setenv("EMBY_API_KEY", "process-key")
    process_config = Config.from_env(tmp_path)
    assert process_config.EMBY_API_KEY == "process-key"


def test_bootstrap_save_failure_preserves_previous_file(tmp_path: Path, monkeypatch) -> None:
    path = save_bootstrap_config(tmp_path, {"EMBY_API_KEY": "old-key"})
    previous = path.read_text(encoding="utf-8")

    def fail_replace(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_bootstrap_config(tmp_path, {"EMBY_API_KEY": "new-key"})

    assert path.read_text(encoding="utf-8") == previous
    assert list(path.parent.glob("bootstrap.json.*.tmp")) == []


def test_bootstrap_save_attempts_restrictive_permissions(tmp_path: Path, monkeypatch) -> None:
    chmod_calls: list[tuple[Path, int]] = []

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))

    monkeypatch.setattr(Path, "chmod", record_chmod)

    saved = save_bootstrap_config(tmp_path, {"EMBY_API_KEY": "saved-key"})

    assert (tmp_path / "data", 0o700) in chmod_calls
    assert (saved, 0o600) in chmod_calls
    assert len([path for path, mode in chmod_calls if mode == 0o600 and path != saved]) == 1


def test_setup_attempt_limiter_uses_fixed_peer_windows() -> None:
    now = [0.0]
    limiter = SetupAttemptLimiter(
        peer_limit=2, global_limit=100, window_seconds=10, clock=lambda: now[0]
    )

    assert limiter.record_failure("peer").allowed is True
    now[0] = 9.0
    assert limiter.record_failure("peer").allowed is True
    limited = limiter.record_failure("peer")
    assert limited.allowed is False
    assert limited.retry_after == 1

    now[0] = 10.0
    assert limiter.record_failure("peer").allowed is True


def test_setup_attempt_limiter_enforces_global_window_across_peers() -> None:
    limiter = SetupAttemptLimiter(peer_limit=5, global_limit=3, window_seconds=10)

    assert limiter.record_failure("peer-1").allowed is True
    assert limiter.record_failure("peer-2").allowed is True
    assert limiter.record_failure("peer-3").allowed is True
    assert limiter.record_failure("peer-4").allowed is False
