"""Browser uploads and settings must never use an operator's working data."""

from pathlib import Path

import pytest

from backend.src.config import EnvConfig
from scripts.run_e2e_app import create_e2e_app
from tests.support.credentials import TEST_SESSION_SECRET


def test_browser_runner_uses_its_root_for_settings_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested_roots: list[Path] = []

    def environment(_cls, project_root: Path):
        requested_roots.append(project_root)
        return EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL="http://127.0.0.1:5012",
            APP_ENV="development",
            MEDIA_SERVER_API_KEY="test-key",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        )

    monkeypatch.setattr(EnvConfig, "from_env", classmethod(environment))
    application = create_e2e_app(tmp_path)
    config = application.state.bootstrap_config
    config.update_runtime({"MAX_USERS_PER_PARTY": 17})

    assert requested_roots == [tmp_path]
    assert application.state.project_root == tmp_path
    assert (tmp_path / "config.json").is_file()
    assert config.MAX_USERS_PER_PARTY == 17
    assert config.LOG_TO_FILE is False
