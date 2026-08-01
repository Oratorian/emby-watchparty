from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.observability import RequestLogMiddleware


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args)


def test_route_log_has_context_without_sensitive_query_values():
    app = FastAPI()
    logger = _Logger()
    app.state.logger = logger
    app.add_middleware(RequestLogMiddleware)

    @app.get("/api/example")
    def example():
        return {"ok": True}

    response = TestClient(app).get(
        "/api/example?token=complete-secret-token&recovery_code=secret-code"
    )

    assert response.status_code == 200
    record = logger.messages[-1]
    assert "route=/api/example" in record
    assert "latency_ms=" in record
    assert "outcome=200" in record
    assert "complete-secret-token" not in record
    assert "secret-code" not in record
