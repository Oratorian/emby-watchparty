import asyncio
from urllib.parse import urlsplit

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.domain import UserStream
from backend.src.providers.models import PlaybackRequest, ProviderCredentials
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN, TEST_SESSION_SECRET
from tests.support.fake_jellyfin import FakeJellyfinState, create_fake_jellyfin_app


def test_jellyfin_master_playlist_uses_bound_opaque_resources(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="",
            EMBY_API_KEY="",
            MEDIA_SERVER_TYPE="jellyfin",
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=True,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create", json={"client_id": "client-1", "display_name": "Alice"}
            )
            party_id = created.json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )
            plan = await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                )
            )
            app.state.hls_registry.install(plan)
            party = app.state.party_manager.get(party_id)
            assert party is not None
            sid = "socket-1"
            party.sid_client_ids[sid] = "client-1"
            party.user_streams[sid] = UserStream(
                media_source_id=plan.media_source_id,
                play_session_id=plan.play_session_id,
                stream_url_base=f"/hls/{plan.stream_id}/master.m3u8",
                stream_id=plan.stream_id,
            )
            token = app.state.token_manager.generate(party_id, sid)
            assert token is not None

            response = await client.get(f"/hls/{plan.stream_id}/master.m3u8?token={token}")

            assert response.status_code == 200
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.text.count(f"/hls/{plan.stream_id}/resources/") == 2
            assert response.text.count(f"?token={token}") == 2
            assert "jellyfin.test" not in response.text
            assert TEST_JELLYFIN_ACCESS_TOKEN not in response.text
            assert "api_key" not in response.text
            assert "subs/en.M3U8" not in response.text
            assert "main.M3U8" not in response.text

    asyncio.run(exercise())
    assert not any(TEST_JELLYFIN_ACCESS_TOKEN in str(row) for row in fake_state.requests)


def test_jellyfin_nested_playlist_is_fetched_by_registered_resource_id(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="",
            EMBY_API_KEY="",
            MEDIA_SERVER_TYPE="jellyfin",
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=True,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create", json={"client_id": "client-1", "display_name": "Alice"}
            )
            party_id = created.json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )
            plan = await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                )
            )
            app.state.hls_registry.install(plan)
            party = app.state.party_manager.get(party_id)
            assert party is not None
            sid = "socket-1"
            party.sid_client_ids[sid] = "client-1"
            party.user_streams[sid] = UserStream(
                media_source_id=plan.media_source_id,
                play_session_id=plan.play_session_id,
                stream_url_base=f"/hls/{plan.stream_id}/master.m3u8",
                stream_id=plan.stream_id,
            )
            token = app.state.token_manager.generate(party_id, sid)
            assert token is not None

            master = await client.get(f"/hls/{plan.stream_id}/master.m3u8?token={token}")
            nested_url = next(
                line for line in master.text.splitlines() if line and not line.startswith("#")
            )
            nested = await client.get(nested_url)

            assert nested.status_code == 200
            segment_url = next(
                line for line in nested.text.splitlines() if line and not line.startswith("#")
            )
            assert urlsplit(segment_url).path.startswith(f"/hls/{plan.stream_id}/resources/")
            assert dict(httpx.QueryParams(urlsplit(segment_url).query)) == {"token": token}
            assert "segment0001.ts" not in nested.text
            assert TEST_JELLYFIN_ACCESS_TOKEN not in nested.text

    asyncio.run(exercise())


def test_jellyfin_opaque_segment_forwards_byte_range(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="",
            EMBY_API_KEY="",
            MEDIA_SERVER_TYPE="jellyfin",
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=True,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create", json={"client_id": "client-1", "display_name": "Alice"}
            )
            party_id = created.json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )
            plan = await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                )
            )
            app.state.hls_registry.install(plan)
            party = app.state.party_manager.get(party_id)
            assert party is not None
            sid = "socket-1"
            party.sid_client_ids[sid] = "client-1"
            party.user_streams[sid] = UserStream(
                media_source_id=plan.media_source_id,
                play_session_id=plan.play_session_id,
                stream_url_base=f"/hls/{plan.stream_id}/master.m3u8",
                stream_id=plan.stream_id,
            )
            token = app.state.token_manager.generate(party_id, sid)
            assert token is not None

            master = await client.get(f"/hls/{plan.stream_id}/master.m3u8?token={token}")
            nested_url = next(
                line for line in master.text.splitlines() if line and not line.startswith("#")
            )
            nested = await client.get(nested_url)
            segment_url = next(
                line for line in nested.text.splitlines() if line and not line.startswith("#")
            )

            segment = await client.get(segment_url, headers={"Range": "bytes=2-5"})

            assert segment.status_code == 206
            assert segment.content == b"2345"
            assert segment.headers["content-range"] == "bytes 2-5/10"
            assert segment.headers["accept-ranges"] == "bytes"
            assert segment.headers["content-length"] == "4"
            assert segment.headers["x-content-type-options"] == "nosniff"

    asyncio.run(exercise())
    segment_request = next(
        row for row in fake_state.requests if row["path"].endswith("/segment0001.ts")
    )
    assert segment_request["query"] == {"part": "1"}


def test_jellyfin_opaque_segment_supports_head_without_body(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="",
            EMBY_API_KEY="",
            MEDIA_SERVER_TYPE="jellyfin",
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=True,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create", json={"client_id": "client-1", "display_name": "Alice"}
            )
            party_id = created.json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )
            plan = await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                )
            )
            app.state.hls_registry.install(plan)
            party = app.state.party_manager.get(party_id)
            assert party is not None
            sid = "socket-1"
            party.sid_client_ids[sid] = "client-1"
            party.user_streams[sid] = UserStream(
                media_source_id=plan.media_source_id,
                play_session_id=plan.play_session_id,
                stream_url_base=f"/hls/{plan.stream_id}/master.m3u8",
                stream_id=plan.stream_id,
            )
            token = app.state.token_manager.generate(party_id, sid)
            assert token is not None

            master_head = await client.head(f"/hls/{plan.stream_id}/master.m3u8?token={token}")
            assert master_head.status_code == 200
            assert master_head.content == b""
            assert master_head.headers["x-content-type-options"] == "nosniff"

            master = await client.get(f"/hls/{plan.stream_id}/master.m3u8?token={token}")
            nested_url = next(
                line for line in master.text.splitlines() if line and not line.startswith("#")
            )
            nested = await client.get(nested_url)
            segment_url = next(
                line for line in nested.text.splitlines() if line and not line.startswith("#")
            )

            response = await client.head(segment_url)

            assert response.status_code == 200
            assert response.content == b""
            assert response.headers["content-length"] == "10"
            assert response.headers["accept-ranges"] == "bytes"
            assert response.headers["x-content-type-options"] == "nosniff"

    asyncio.run(exercise())
    master_request = next(
        row
        for row in fake_state.requests
        if row["path"].endswith("/master.m3u8") and row["method"] == "HEAD"
    )
    assert master_request["query"]["PlaySessionId"] == "jellyfin-play-session-1"
    request = next(
        row
        for row in fake_state.requests
        if row["path"].endswith("/segment0001.ts") and row["method"] == "HEAD"
    )
    assert request["query"] == {"part": "1"}
