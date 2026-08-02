import json
import os
from pathlib import Path

import pytest

from backend.src.bootstrap import save_bootstrap_config
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
