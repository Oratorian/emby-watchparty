"""Run an isolated dev-host backend for browser refresh regressions."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig


def create_dev_host_e2e_app(root: Path):
    """Use only synthetic settings and disposable configuration and data."""

    class BrowserRuntimeConfig(RuntimeConfig):
        def save(self, path: Path | None = None):
            return super().save(path or root / "config.json")

    # Resolve against a new temporary root and an explicit environment mapping,
    # so neither the operator's .env nor their process credentials are read.
    env = EnvConfig.from_env(
        root,
        environ={
            "APP_ENV": "development",
            "MEDIA_SERVER_TYPE": "emby",
            "MEDIA_SERVER_URL": "http://127.0.0.1:5012",
            "MEDIA_SERVER_API_KEY": "e2e-key",
            "SESSION_SECRET": "playwright-dev-host-session-secret-at-least-32-characters",
            "SESSION_COOKIE_SECURE": "false",
            "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:4174",
            "BEHIND_PROXY": "false",
        },
    )
    config = Config(
        env,
        BrowserRuntimeConfig(ENABLE_RATE_LIMITING=False, LOG_TO_FILE=False),
        private_env={
            "EMBY_WATCHPARTY_X_DEV_HOST": "Alice:password",
            "EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK": "true",
        },
    )
    return create_app(config=config, project_root=root, enable_update_check=False)


if __name__ == "__main__":
    import uvicorn

    with TemporaryDirectory(prefix="ewp-dev-host-browser-") as directory:
        uvicorn.run(
            create_dev_host_e2e_app(Path(directory)),
            host="127.0.0.1",
            port=5014,
            proxy_headers=False,
            log_level="warning",
        )
