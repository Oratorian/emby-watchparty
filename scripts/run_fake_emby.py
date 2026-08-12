"""Run the shared fake Emby boundary for browser tests."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support.fake_emby import create_fake_emby_app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_fake_emby_app(),
        # Loopback by default: this serves an unauthenticated fake Emby, so a
        # developer running the browser suite must not publish it to their
        # network. CI's container job overrides it, because the application
        # under test runs in Docker and reaches the host over the bridge
        # gateway (host.docker.internal -> 172.17.0.1 on Linux), which a
        # loopback-only listener refuses.
        host=os.getenv("E2E_FAKE_EMBY_HOST", "127.0.0.1"),
        port=int(os.getenv("E2E_FAKE_EMBY_PORT", "5012")),
        proxy_headers=False,
        log_level="warning",
    )
