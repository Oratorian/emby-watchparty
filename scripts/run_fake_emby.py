"""Run the shared fake Emby boundary for browser tests."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support.fake_emby import create_fake_emby_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_fake_emby_app(),
        host="127.0.0.1",
        port=int(os.getenv("E2E_FAKE_EMBY_PORT", "5012")),
        proxy_headers=False,
        log_level="warning",
    )
