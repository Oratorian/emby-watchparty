import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.rate_limit import (
    RateLimitMiddleware,
    SlidingWindowRateLimiter,
    parse_rate,
)


class _Config:
    APP_PREFIX = ""
    ENABLE_RATE_LIMITING = True
    RATE_LIMIT_API_CALLS = "2 per minute"
    RATE_LIMIT_PARTY_CREATION = "1 per hour"
    TRUSTED_PROXY_CIDRS = ()


class RateLimitingTests(unittest.TestCase):
    def test_zero_limit_is_rejected_instead_of_crashing_request_handling(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            parse_rate("0 per minute")

    def test_general_api_limit_returns_429_with_retry_after(self):
        app = FastAPI()
        app.state.config = _Config()
        app.state.rate_limiter = SlidingWindowRateLimiter()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/example")
        def example():
            return {"ok": True}

        client = TestClient(app)
        self.assertEqual(client.get("/api/example").status_code, 200)
        self.assertEqual(client.get("/api/example").status_code, 200)
        limited = client.get("/api/example")

        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["retry-after"]), 0)

    def test_party_creation_uses_stricter_limit(self):
        app = FastAPI()
        app.state.config = _Config()
        app.state.rate_limiter = SlidingWindowRateLimiter()
        app.add_middleware(RateLimitMiddleware)

        @app.post("/api/party/create")
        def create():
            return {"ok": True}

        client = TestClient(app)
        self.assertEqual(client.post("/api/party/create").status_code, 200)
        self.assertEqual(client.post("/api/party/create").status_code, 429)

    def test_rate_limit_honors_application_prefix(self):
        app = FastAPI()
        config = _Config()
        config.APP_PREFIX = "/watchparty"
        app.state.config = config
        app.state.rate_limiter = SlidingWindowRateLimiter()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/watchparty/api/example")
        def example():
            return {"ok": True}

        client = TestClient(app)
        self.assertEqual(client.get("/watchparty/api/example").status_code, 200)
        self.assertEqual(client.get("/watchparty/api/example").status_code, 200)
        self.assertEqual(client.get("/watchparty/api/example").status_code, 429)


if __name__ == "__main__":
    unittest.main()
