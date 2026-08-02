import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client


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
            SESSION_SECRET="short",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def _valid_setup_payload() -> dict:
    return {
        "APP_ENV": "production",
        "EMBY_SERVER_URL": "https://emby.example",
        "EMBY_API_KEY": "new-api-key",
        "SESSION_SECRET": "n" * 64,
        "SESSION_COOKIE_SECURE": True,
        "CORS_ALLOWED_ORIGINS": ["https://watch.example"],
        "TRUSTED_PROXY_CIDRS": ["10.0.0.0/8"],
        "APP_PREFIX": "",
        "ENABLE_HLS_TOKEN_VALIDATION": True,
    }


def test_invalid_production_config_serves_setup_instead_of_raising(tmp_path: Path) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.get("/setup")
            assert response.status_code == 200
            assert "First-run configuration" in response.text

    asyncio.run(exercise())


def test_config_loads_persisted_bootstrap_values(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "bootstrap.json").write_text(
        json.dumps(
            {
                "APP_ENV": "production",
                "EMBY_SERVER_URL": "https://emby.example",
                "EMBY_API_KEY": "saved-key",
                "SESSION_SECRET": "s" * 64,
                "SESSION_COOKIE_SECURE": True,
                "CORS_ALLOWED_ORIGINS": ["https://watch.example"],
                "TRUSTED_PROXY_CIDRS": [],
                "APP_PREFIX": "/watch",
                "ENABLE_HLS_TOKEN_VALIDATION": True,
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "APP_ENV",
        "EMBY_SERVER_URL",
        "EMBY_API_KEY",
        "SESSION_SECRET",
        "SESSION_COOKIE_SECURE",
        "CORS_ALLOWED_ORIGINS",
        "TRUSTED_PROXY_CIDRS",
        "APP_PREFIX",
        "ENABLE_HLS_TOKEN_VALIDATION",
    ):
        monkeypatch.delenv(name, raising=False)

    config = Config.from_env(project_root=tmp_path)

    assert config.APP_ENV == "production"
    assert config.EMBY_API_KEY == "saved-key"
    assert config.APP_PREFIX == "/watch"
    config.validate_for_startup()


def test_malformed_boot_value_enters_setup_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WATCH_PARTY_PORT", "not-a-port")

    app = create_app(project_root=tmp_path, enable_update_check=False)
    assert not hasattr(app.state, "sio")

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.get("/setup")
            assert "First-run configuration" in response.text

    asyncio.run(exercise())


def test_setup_mode_exposes_only_setup_and_probe_routes(tmp_path: Path) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            root = await client.get("/", follow_redirects=False)
            assert root.status_code == 307
            assert root.headers["location"] == "/setup"
            assert (await client.get("/api/health")).status_code == 200
            ready = await client.get("/api/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "setup_required"}
            for path in (
                "/api/party/list",
                "/hls/item/master.m3u8",
                "/admin",
                "/assets/app.js",
                "/socket.io/?EIO=4&transport=polling",
                "/docs",
            ):
                assert (await client.get(path)).status_code == 503

    asyncio.run(exercise())


def test_setup_write_requires_console_bootstrap_token(tmp_path: Path, capsys) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )
    console = capsys.readouterr().out
    match = re.search(r"Bootstrap token: ([A-Za-z0-9_-]+)", console)
    assert match is not None
    token = match.group(1)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            page = await client.get("/setup")
            assert token not in page.text
            missing = await client.post("/api/setup", json={})
            wrong = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": "wrong"},
                json={},
            )
            correct = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json={},
            )
            assert missing.status_code == 403
            assert wrong.status_code == 403
            assert correct.status_code == 400
            assert token not in missing.text + wrong.text + correct.text

    asyncio.run(exercise())


def test_failed_bootstrap_token_attempts_are_rate_limited(tmp_path: Path, capsys) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )
    token = re.search(
        r"Bootstrap token: ([A-Za-z0-9_-]+)", capsys.readouterr().out
    ).group(1)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            for attempt in range(5):
                response = await client.post(
                    "/api/setup",
                    headers={"X-Emby-Watchparty-Setup-Token": f"wrong-{attempt}"},
                    json={},
                )
                assert response.status_code == 403
            limited = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": "wrong-again"},
                json={},
            )
            assert limited.status_code == 429
            assert int(limited.headers["Retry-After"]) > 0
            correct = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json={},
            )
            assert correct.status_code == 400

    asyncio.run(exercise())


def test_saved_configuration_enters_normal_mode_after_restart(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )
    token = re.search(
        r"Bootstrap token: ([A-Za-z0-9_-]+)", capsys.readouterr().out
    ).group(1)

    async def save() -> None:
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json=_valid_setup_payload(),
            )
            assert response.status_code == 200
            assert response.json() == {"status": "saved", "restart_required": True}
            assert "new-api-key" not in response.text
            assert "n" * 64 not in response.text
            repeated = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json=_valid_setup_payload(),
            )
            assert repeated.status_code == 409

    asyncio.run(save())
    for name in _valid_setup_payload():
        monkeypatch.delenv(name, raising=False)
    saved = json.loads((tmp_path / "data" / "bootstrap.json").read_text(encoding="utf-8"))
    assert saved["EMBY_API_KEY"] == "new-api-key"

    restarted = create_app(project_root=tmp_path, enable_update_check=False)
    assert hasattr(restarted.state, "sio")


def test_invalid_setup_fields_return_safe_errors(tmp_path: Path, capsys, caplog) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )
    token = re.search(
        r"Bootstrap token: ([A-Za-z0-9_-]+)", capsys.readouterr().out
    ).group(1)
    payload = _valid_setup_payload()
    payload["SESSION_SECRET"] = "leaky-short-secret"
    payload["EMBY_API_KEY"] = "   "

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json=payload,
            )
            assert response.status_code == 400
            assert set(response.json()["errors"]) >= {"SESSION_SECRET", "EMBY_API_KEY"}
            assert "leaky-short-secret" not in response.text

    asyncio.run(exercise())
    assert "leaky-short-secret" not in caplog.text


def test_setup_page_contains_secure_configuration_form(tmp_path: Path, capsys) -> None:
    app = create_app(
        config=_invalid_production_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )
    token = re.search(
        r"Bootstrap token: ([A-Za-z0-9_-]+)", capsys.readouterr().out
    ).group(1)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.get("/setup")
            assert response.status_code == 200
            for field in _valid_setup_payload():
                assert f'name="{field}"' in response.text
            assert 'name="BOOTSTRAP_TOKEN"' in response.text
            assert "crypto.getRandomValues" in response.text
            assert "Generate secure secret" in response.text
            assert "localStorage" not in response.text
            assert token not in response.text
            assert "Boot-setting changes require restart" in response.text

    asyncio.run(exercise())


def test_setup_routes_honor_app_prefix_and_skip_normal_resources(
    tmp_path: Path, capsys
) -> None:
    app = create_app(
        config=_invalid_production_config(prefix="/watch"),
        project_root=tmp_path,
        enable_update_check=False,
    )
    capsys.readouterr()
    assert not hasattr(app.state, "sio")
    assert not hasattr(app.state, "party_manager")
    assert not hasattr(app.state, "token_manager")
    assert not hasattr(app.state, "admin_session_store")

    async def exercise() -> None:
        async with asgi_client(app) as client:
            root = await client.get("/", follow_redirects=False)
            assert root.headers["location"] == "/watch/setup"
            assert (await client.get("/watch/setup")).status_code == 200
            assert (await client.get("/watch/api/health")).status_code == 200
            assert (await client.get("/watch/api/ready")).status_code == 503
            assert (await client.get("/api/health")).status_code == 503

    asyncio.run(exercise())


def test_invalid_app_prefix_falls_back_to_unprefixed_setup(tmp_path: Path) -> None:
    app = create_app(
        config=_invalid_production_config(prefix="not/absolute"),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            assert (await client.get("/setup")).status_code == 200

    asyncio.run(exercise())


def test_invalid_environment_override_cannot_be_masked_by_setup(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    persisted = _valid_setup_payload()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "bootstrap.json").write_text(
        json.dumps(persisted), encoding="utf-8"
    )
    monkeypatch.setenv("SESSION_SECRET", "invalid-env-secret")
    app = create_app(project_root=tmp_path, enable_update_check=False)
    token = re.search(
        r"Bootstrap token: ([A-Za-z0-9_-]+)", capsys.readouterr().out
    ).group(1)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/setup",
                headers={"X-Emby-Watchparty-Setup-Token": token},
                json=_valid_setup_payload(),
            )
            assert response.status_code == 400
            assert response.json()["errors"]["SESSION_SECRET"] == (
                "Invalid environment override; change or remove it and restart"
            )

    asyncio.run(exercise())
    assert json.loads((tmp_path / "data" / "bootstrap.json").read_text(encoding="utf-8")) == persisted


def test_corrupted_persisted_bootstrap_enters_setup_mode(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "bootstrap.json").write_text("{broken", encoding="utf-8")

    app = create_app(project_root=tmp_path, enable_update_check=False)
    assert not hasattr(app.state, "sio")

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.get("/setup")
            assert "First-run configuration" in response.text

    asyncio.run(exercise())


def test_module_import_survives_setup_mode() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "SESSION_SECRET": "short",
            "SESSION_COOKIE_SECURE": "false",
            "CORS_ALLOWED_ORIGINS": "*",
            "APP_PREFIX": "",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import backend.app; assert backend.app.sio is None"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
