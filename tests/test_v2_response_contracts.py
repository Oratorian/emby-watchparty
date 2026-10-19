"""Check the response bodies that were missing from Swagger and ReDoc."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.providers.models import PlaybackPlanError
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET
from tests.support.fake_emby import create_fake_emby_app


def _application(tmp_path: Path, runtime: RuntimeConfig | None = None):
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL="http://emby.test",
            MEDIA_SERVER_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        runtime or RuntimeConfig(LOG_TO_FILE=False),
    )
    return create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_emby_app()),
    )


async def _join(client: httpx.AsyncClient) -> str:
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    joined = await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "response-host", "display_name": "Alice"},
    )
    assert joined.json()["success"] is True
    return party_id


async def _login(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v2/auth/login", json={"username": "Alice", "password": "password"}
    )
    assert response.json()["success"] is True


def _response_schema(application, path: str, status: int, *, method: str = "get"):
    return application.openapi()["paths"][path][method]["responses"][str(status)]


def _assert_detail_response(application, path: str, response: httpx.Response, *, method="get"):
    documented = _response_schema(application, path, response.status_code, method=method)
    assert documented["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HTTPErrorResponse"
    }
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)
    assert body["detail"]


def test_v2_guard_and_upstream_failures_publish_their_actual_json_bodies(
    tmp_path: Path, monkeypatch
) -> None:
    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            unauthenticated = await client.get("/api/v2/libraries")
            assert unauthenticated.status_code == 401
            _assert_detail_response(application, "/api/v2/libraries", unauthenticated)

            party_id = await _join(client)
            locked = await client.get("/api/v2/libraries")
            assert locked.status_code == 423
            _assert_detail_response(application, "/api/v2/libraries", locked)

            await _login(client)
            monkeypatch.setattr(
                application.state.media_server, "get_details", AsyncMock(return_value=None)
            )
            missing = await client.get("/api/v2/items/no-such-item")
            assert missing.status_code == 404
            _assert_detail_response(application, "/api/v2/items/{item_id}", missing)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://testserver"
            ) as guest:
                await guest.post(
                    f"/api/party/{party_id}/join",
                    json={"client_id": "response-guest", "display_name": "Bob"},
                )
                forbidden = await guest.put(
                    "/api/v2/items/movie-1/favorite", json={"favorite": True}
                )
            assert forbidden.status_code == 403
            _assert_detail_response(
                application, "/api/v2/items/{item_id}/favorite", forbidden, method="put"
            )

            monkeypatch.setattr(
                application.state.media_server,
                "browse_libraries",
                AsyncMock(side_effect=httpx.ConnectError("offline")),
            )
            unavailable = await client.get("/api/v2/libraries")
            assert unavailable.status_code == 502
            _assert_detail_response(application, "/api/v2/libraries", unavailable)

    asyncio.run(exercise())


def test_v2_stream_negotiation_failure_has_the_same_documented_error_shape(
    tmp_path: Path, monkeypatch
) -> None:
    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            await _join(client)
            await _login(client)
            monkeypatch.setattr(
                application.state.media_server,
                "get_streams",
                AsyncMock(side_effect=PlaybackPlanError("no playable source")),
            )
            response = await client.get("/api/v2/items/movie-1/streams")
            assert response.status_code == 502
            _assert_detail_response(application, "/api/v2/items/{item_id}/streams", response)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("path", "documented_path", "media_type", "documented_media_type", "content"),
    [
        (
            "/api/v2/items/movie-1/images/primary",
            "/api/v2/items/{item_id}/images/{image_type}",
            "image/avif",
            "image/*",
            b"image bytes",
        ),
        (
            "/api/v2/items/movie-1/subtitles/source-1/3",
            "/api/v2/items/{item_id}/subtitles/{media_source_id}/{subtitle_index}",
            "text/vtt",
            "text/vtt",
            b"WEBVTT\n\n",
        ),
    ],
)
def test_v2_assets_document_bytes_and_both_not_found_responses(
    tmp_path: Path,
    monkeypatch,
    path: str,
    documented_path: str,
    media_type: str,
    documented_media_type: str,
    content: bytes,
) -> None:
    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            party_id = await _join(client)
            await _login(client)
            fetch_asset = AsyncMock(
                return_value=httpx.Response(
                    200, content=content, headers={"Content-Type": media_type}
                )
            )
            monkeypatch.setattr(application.state.media_server, "fetch_asset", fetch_asset)

            response = await client.get(path)
            assert response.status_code == 200
            assert response.content == content
            assert response.headers["content-type"].startswith(media_type)
            documented = _response_schema(application, documented_path, 200)
            assert "application/json" not in documented["content"]
            assert documented["content"][documented_media_type]["schema"] == {
                "type": "string",
                "format": "binary",
            }

            fetch_asset.return_value = httpx.Response(404)
            missing_asset = await client.get(path)
            assert missing_asset.status_code == 404
            assert missing_asset.content == b""
            assert "content-type" not in missing_asset.headers
            assert (
                "empty body" in _response_schema(application, documented_path, 404)["description"]
            )

            await application.state.party_manager.pop_party(party_id)
            missing_party = await client.get(path)
            assert missing_party.status_code == 404
            _assert_detail_response(application, documented_path, missing_party)

    asyncio.run(exercise())


def test_v2_api_limit_publishes_json_and_retry_after(tmp_path: Path) -> None:
    async def exercise() -> None:
        application = _application(
            tmp_path, RuntimeConfig(LOG_TO_FILE=False, RATE_LIMIT_API_CALLS="1 per minute")
        )
        async with asgi_client(application) as client:
            assert (await client.get("/api/v2/media-server")).status_code == 200
            response = await client.get("/api/v2/media-server")

        assert response.status_code == 429
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["code"] == "rate_limited"
        assert body["retry_after"] == int(response.headers["retry-after"])
        assert body["retry_after"] > 0
        documented = _response_schema(application, "/api/v2/media-server", 429)
        assert documented["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/RateLimitResponse"
        }
        assert documented["headers"]["Retry-After"]["schema"]["type"] == "integer"

    asyncio.run(exercise())


def test_v2_response_defaults_are_required_without_requiring_request_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            await _join(client)
            await _login(client)
            monkeypatch.setattr(
                application.state.media_server, "get_intro", AsyncMock(return_value=None)
            )
            intro = await client.get("/api/v2/items/movie-1/intro")
            assert intro.json() == {
                "has_intro": False,
                "start_seconds": None,
                "end_seconds": None,
                "duration_seconds": None,
            }
            document = application.openapi()
            schema_ref = _response_schema(application, "/api/v2/items/{item_id}/intro", 200)[
                "content"
            ]["application/json"]["schema"]["$ref"]
            schema = document["components"]["schemas"][schema_ref.rsplit("/", 1)[1]]
            assert set(schema["required"]) == set(intro.json())

            # Query defaults belong to the input contract, where omitting them
            # must remain valid even though output defaults are always present.
            queried = await client.post("/api/v2/items/query", json={})
            assert queried.status_code == 200
            request_ref = document["paths"]["/api/v2/items/query"]["post"]["requestBody"][
                "content"
            ]["application/json"]["schema"]["$ref"]
            request_schema = document["components"]["schemas"][request_ref.rsplit("/", 1)[1]]
            assert not request_schema.get("required")

    asyncio.run(exercise())


def test_every_documented_v2_error_has_a_body_schema(tmp_path: Path) -> None:
    document = _application(tmp_path).openapi()
    failures = []
    for path, methods in document["paths"].items():
        if not path.startswith("/api/v2/"):
            continue
        for method, operation in methods.items():
            for status, response in operation["responses"].items():
                if status in {"401", "403", "404", "423", "429", "502"} and not response.get(
                    "content", {}
                ).get("application/json", {}).get("schema"):
                    failures.append(f"{method.upper()} {path}: {status}")
    assert not failures, "Missing v2 response schemas: " + ", ".join(failures)
