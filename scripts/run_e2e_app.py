"""Run the backend for Playwright without external update traffic."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig


if __name__ == "__main__":
    import uvicorn

    # Browser workers share this loopback process and therefore one source IP.
    # Limits have dedicated public tests; disabling them here keeps independent
    # Playwright scenarios isolated when the runner executes in parallel.
    config = Config(EnvConfig.from_env(), RuntimeConfig(ENABLE_RATE_LIMITING=False))
    uvicorn.run(
        create_app(config=config, enable_update_check=False),
        host="127.0.0.1",
        port=int(os.getenv("E2E_BACKEND_PORT", "5011")),
        proxy_headers=False,
        log_level="warning",
    )
