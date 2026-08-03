"""Unconfigured mode: what happens when boot configuration is invalid.

Configuration is environment-only. There is no setup form and no
bootstrap token, so these tests cover the whole of what remains: name
the bad fields loudly, answer probes so an orchestrator can diagnose
rather than restart-loop, and serve nothing else.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from backend.app import _json_for_html_script, create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client
from tests.support.credentials import REJECTED_SESSION_SECRET


def _invalid_production_config(*, prefix: str = "") -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX=prefix,
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="production",
            SESSION_SECRET=REJECTED_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def _unconfigured_environment() -> dict[str, str]:
    """An environment whose boot config does not validate."""
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "SESSION_SECRET": REJECTED_SESSION_SECRET,
            "SESSION_COOKIE_SECURE": "false",
            "CORS_ALLOWED_ORIGINS": "*",
            "APP_PREFIX": "",
        }
    )
    return environment


def test_invalid_config_serves_a_diagnosis_instead_of_raising(tmp_path: Path) -> None:
    """A misconfigured container must stay up and stay diagnosable.

    Raising would restart-loop under `restart: unless-stopped`, which
    buries the reason in a scrolling log.
    """
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            health = await client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "setup_required"

            ready = await client.get("/api/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "setup_required"}

    asyncio.run(exercise())


def test_unconfigured_mode_serves_nothing_else(tmp_path: Path) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            for path in (
                "/",
                "/setup",
                "/api/setup",
                "/api/party/list",
                "/hls/item/master.m3u8",
                "/admin",
                "/assets/app.js",
                "/socket.io/?EIO=4&transport=polling",
                "/docs",
            ):
                assert (await client.get(path)).status_code == 503, path

    asyncio.run(exercise())


def test_the_failing_fields_are_named_on_stderr(tmp_path: Path, capsys) -> None:
    """The banner is the only diagnosis an operator now gets.

    On Unraid, CasaOS, Portainer and TrueNAS this is read through a web
    log viewer, so it has to be findable among startup noise and it has
    to say which fields are wrong, not merely that something is.
    """
    create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    printed = capsys.readouterr().err
    assert "invalid boot configuration" in printed
    for field in ("SESSION_SECRET", "SESSION_COOKIE_SECURE", "CORS_ALLOWED_ORIGINS"):
        assert field in printed, f"{field} is invalid but was not named"
    assert "environment" in printed, "operator is not told where to fix it"


def test_malformed_boot_value_enters_unconfigured_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WATCH_PARTY_PORT", "not-a-port")

    app = create_app(project_root=tmp_path, enable_update_check=False)
    assert not hasattr(app.state, "sio")

    async def exercise() -> None:
        async with asgi_client(app) as client:
            assert (await client.get("/api/ready")).status_code == 503

    asyncio.run(exercise())


def test_invalid_app_prefix_falls_back_to_unprefixed_probes(tmp_path: Path) -> None:
    """An invalid APP_PREFIX must not make the diagnosis unreachable."""
    app = create_app(
        config=_invalid_production_config(prefix="not a prefix"),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            assert (await client.get("/api/health")).json()["status"] == "setup_required"

    asyncio.run(exercise())


def test_probes_honour_a_valid_app_prefix(tmp_path: Path) -> None:
    app = create_app(
        config=_invalid_production_config(prefix="/watchparty"),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            prefixed = await client.get("/watchparty/api/health")
            assert prefixed.json()["status"] == "setup_required"
            assert (await client.get("/api/health")).status_code == 503

    asyncio.run(exercise())


def test_stale_bootstrap_artefacts_are_ignored_and_removed(tmp_path: Path, monkeypatch) -> None:
    """Configuration is environment-only.

    The interactive flow persisted `data/bootstrap.json` and a
    `data/setup-token`. A leftover from a 3.0 development build must not
    resurrect either mechanism, and the token in particular must not be
    left lying on disk once the app boots normally.
    """
    for name in ("APP_ENV", "SESSION_SECRET", "SESSION_COOKIE_SECURE", "CORS_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)

    data = tmp_path / "data"
    data.mkdir()
    (data / "bootstrap.json").write_text(
        '{"CONFIGURED": true, "APP_ENV": "production", "EMBY_API_KEY": "from-stale-file"}',
        encoding="utf-8",
    )
    (data / "setup-token").write_text("stale-token\n", encoding="utf-8")

    config = Config.from_env(project_root=tmp_path)
    assert config.EMBY_API_KEY != "from-stale-file", "persisted file was still being read"

    create_app(project_root=tmp_path, enable_update_check=False)
    assert not (data / "setup-token").exists(), "stale setup token left on disk"
    assert not (data / "bootstrap.json").exists(), "stale bootstrap file left on disk"


def test_inline_script_json_escapes_html_delimiters() -> None:
    """`rendered_index` injects APP_PREFIX into a <script> block.

    Still load-bearing after the setup page was removed, because the SPA
    index injection uses the same helper.
    """
    serialized = _json_for_html_script("/</script><script>&attack</script>")

    assert "</script>" not in serialized
    assert "<" not in serialized
    assert ">" not in serialized
    assert "&" not in serialized


def test_module_import_survives_unconfigured_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import backend.app; assert backend.app.sio is None"],
        capture_output=True,
        text=True,
        env=_unconfigured_environment(),
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_importing_the_module_builds_nothing() -> None:
    """`import backend.app` must not construct an app.

    Nine test modules import this file. While construction happened at
    module scope, every import built an app against ambient config, and
    in the unconfigured case that printed a diagnosis nobody asked for.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import backend.app"],
        capture_output=True,
        text=True,
        env=_unconfigured_environment(),
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "invalid boot configuration" not in result.stderr
