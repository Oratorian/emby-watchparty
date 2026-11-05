"""Run the backend for Playwright without external update traffic."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig


def create_e2e_app(root: Path):
    """Keep browser uploads, configuration and identities in a disposable root."""

    class BrowserRuntimeConfig(RuntimeConfig):
        def save(self, path: Path | None = None):
            return super().save(path or root / "config.json")

    config = Config(
        EnvConfig.from_env(project_root=root),
        BrowserRuntimeConfig(ENABLE_RATE_LIMITING=False, LOG_TO_FILE=False),
    )
    return create_app(config=config, project_root=root, enable_update_check=False)


if __name__ == "__main__":
    import uvicorn

    # Browser workers share this loopback process and therefore one source IP.
    # Limits have dedicated public tests; disabling them here keeps independent
    # Playwright scenarios isolated when the runner executes in parallel.
    with TemporaryDirectory(prefix="ewp-browser-") as directory:
        uvicorn.run(
            create_e2e_app(Path(directory)),
            host="127.0.0.1",
            port=int(os.getenv("E2E_BACKEND_PORT", "5011")),
            proxy_headers=False,
            log_level="warning",
        )
