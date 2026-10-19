"""Published core-router errors must describe the JSON clients actually receive."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.src.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from backend.src.routers import admin, auth, party, quality
from tests.support.credentials import TEST_SESSION_SECRET

CORE_ROUTERS = (admin.router, auth.router, party.router, quality.router)
CORE_OPERATIONS = [
    (method, route.path)
    for router in CORE_ROUTERS
    for route in router.routes
    if isinstance(route, APIRoute)
    for method in sorted(route.methods - {"HEAD", "OPTIONS"})
]


@pytest.fixture
def client():
    # Mount the real routers and limiter without loading operator configuration,
    # launching background tasks, or connecting to an actual media server.
    app = FastAPI()
    config = SimpleNamespace(
        APP_PREFIX="",
        ENABLE_RATE_LIMITING=False,
        RATE_LIMIT_API_CALLS="1 per 15 minutes",
        RATE_LIMIT_PARTY_CREATION="1 per 15 minutes",
        RATE_LIMIT_LOGIN="1 per 15 minutes",
        TRUSTED_PROXY_CIDRS=(),
        STATIC_SESSION_ENABLED=False,
        REQUIRE_LOGIN=False,
        FORCE_TRANSCODE=False,
        ENABLED_QUALITY_OPTIONS={"720p": [4000]},
        get_runtime_dict=lambda: {"LOG_LEVEL": "INFO", "REQUIRE_LOGIN": False},
    )
    app.state.config = config
    app.state.logger = Mock()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.party_manager = SimpleNamespace(
        get=lambda _party_id: None,
        get_all=dict,
        exists=lambda _party_id: False,
        create_party=lambda: "ABCDE",
        static_party_id=None,
    )
    app.state.admin_session_store = SimpleNamespace(get=lambda _handle: None, revoke=Mock())
    app.state.media_server = SimpleNamespace(
        identity=SimpleNamespace(display_name="Emby"),
        authenticate_user=AsyncMock(return_value=None),
    )
    app.state.sio = SimpleNamespace(emit=AsyncMock())
    app.state.http_client = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(status_code=503)),
    )
    app.add_middleware(SessionMiddleware, secret_key=TEST_SESSION_SECRET)
    app.add_middleware(RateLimitMiddleware)
    for router in CORE_ROUTERS:
        app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def _response_contract(client: TestClient, method: str, path: str, status: int) -> dict:
    return client.app.openapi()["paths"][path][method.lower()]["responses"][str(status)]


@pytest.mark.parametrize(("method", "path"), CORE_OPERATIONS)
def test_every_core_operation_documents_the_limiter_response(
    client: TestClient, method: str, path: str
) -> None:
    client.app.state.config.ENABLE_RATE_LIMITING = True
    url = path.replace("{party_id}", "MISSING")
    kwargs = {"json": {}} if method in {"POST", "PUT"} else {}
    client.request(method, url, **kwargs)
    response = client.request(method, url, **kwargs)

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {"detail", "code", "retry_after"}
    assert payload["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) == payload["retry_after"] > 0
    contract = _response_contract(client, method, path, 429)
    assert contract["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RateLimitResponse"
    }
    assert "Retry-After" in contract["headers"]


def test_admin_login_has_the_same_contract_for_its_separate_login_limit(client: TestClient) -> None:
    client.app.state.config.ENABLE_RATE_LIMITING = True
    client.app.state.config.RATE_LIMIT_API_CALLS = "100 per minute"
    credentials = {"username": "Alice", "password": "incorrect"}
    first = client.post("/api/admin/login", json=credentials)
    limited = client.post("/api/admin/login", json=credentials)

    assert first.status_code == 200
    assert first.json() == {"success": False, "message": "Invalid credentials"}
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert "login attempts" in limited.json()["detail"]
    assert int(limited.headers["Retry-After"]) == limited.json()["retry_after"]


def test_party_info_missing_body_matches_the_published_404(client: TestClient) -> None:
    response = client.get("/api/party/MISSING/info")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Party not found"}
    contract = _response_contract(client, "GET", "/api/party/{party_id}/info", 404)
    assert contract["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HTTPErrorResponse"
    }


def test_admin_config_denial_still_uses_the_existing_200_body(client: TestClient) -> None:
    response = client.get("/api/admin/config")

    assert response.status_code == 200
    assert response.json() == {"error": "Not authenticated"}
    contract = _response_contract(client, "GET", "/api/admin/config", 200)
    assert contract["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RuntimeConfigResponse"
    }


def test_runtime_config_success_preserves_dynamic_keys_and_error_null(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin, "is_admin_authenticated", lambda *_args: True)
    response = client.get("/api/admin/config")

    assert response.status_code == 200
    assert response.json() == {"error": None, "LOG_LEVEL": "INFO", "REQUIRE_LOGIN": False}


def test_refused_creation_and_join_keep_their_existing_200_contracts(client: TestClient) -> None:
    client.app.state.config.REQUIRE_LOGIN = True
    created = client.post("/api/party/create", json={})
    joined = client.post(
        "/api/party/MISSING/join", json={"client_id": "viewer", "display_name": "Alice"}
    )

    assert created.status_code == 200
    assert created.json()["party_id"] == created.json()["url"] == ""
    assert created.json()["message"] == "Emby login is required to create a party"
    assert joined.status_code == 200
    assert joined.json()["success"] is False
    assert joined.json()["message"] == "Party not found"


def test_quality_nullable_values_and_version_fallback_keep_their_wire_shapes(
    client: TestClient,
) -> None:
    options = client.get("/api/quality-options")
    version = client.get("/api/version")

    assert options.status_code == 200
    auto = options.json()["options"][0]
    assert auto == {
        "id": "auto",
        "label": "Auto",
        "resolution": None,
        "width": None,
        "height": None,
        "bitrate_kbps": None,
    }
    assert options.json()["default_id"] == "auto"
    assert version.status_code == 200
    assert version.json()["current_version"]
    assert version.json()["latest_version"] is None
    assert version.json()["update_available"] is False
