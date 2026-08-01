"""Run the backend for Playwright without external update traffic."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import create_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_app(enable_update_check=False),
        host="127.0.0.1",
        port=int(os.getenv("E2E_BACKEND_PORT", "5011")),
        proxy_headers=False,
        log_level="warning",
    )
