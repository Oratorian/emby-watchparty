import asyncio
from urllib.parse import urlsplit

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.domain import UserStream
from backend.src.providers.models import HLSResource, PlaybackRequest, ProviderCredentials
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
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
    # No assertion that the token is absent upstream: it belongs there. The
    # proxy authenticates with it via x-emby-token / x-emby-authorization, and
    # Jellyfin's own TranscodingUrl embeds api_key= in the query it hands us.
    #
    # The line that used to sit here checked `TEST_..._TOKEN in str(row)` over
    # the recorded requests, which passed only because the fake redacted
    # api_key and access_token before storing and recorded no headers at all.
    # It asserted the fake's redaction, not the proxy's behaviour, and once the
    # fake began recording raw values it failed -- correctly, because the
    # premise was wrong.
    #
    # The property worth guarding is that none of it reaches the browser, and
    # that is what the response-body assertions above do: the rewriter replaces
    # every upstream URL with an opaque resource id, so a leak shows up there.
    assert any(
        TEST_JELLYFIN_ACCESS_TOKEN in row["headers"].get("x-emby-token", "")
        for row in fake_state.requests
    ), "the proxy stopped authenticating upstream; the rewrite assertions above would still pass"


def test_jellyfin_legacy_hls_fallback_dials_the_configured_media_server(tmp_path) -> None:
    """The unregistered-stream fallback must build its upstream from config.

    This used to set a second, wrong Emby address and prove the selected
    provider's own URL won. 3.0 has one MEDIA_SERVER_URL for both providers,
    so that contrast cannot be expressed; what is still worth pinning is that
    the legacy route composes the address from configuration at all, rather
    than from the localhost default or a hardcoded host.
    """
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
            party = app.state.party_manager.get(party_id)
            assert party is not None
            sid = "socket-1"
            party.sid_client_ids[sid] = "client-1"
            token = app.state.token_manager.generate(party_id, sid)
            assert token is not None

            response = await client.get(f"/hls/movie-1/master.m3u8?token={token}")

            assert response.status_code == 200
            master_request_index = next(
                index
                for index, row in enumerate(fake_state.requests)
                if row["path"].endswith("/master.m3u8")
            )
            assert fake_state.request_hosts[master_request_index] == "jellyfin.test"

    asyncio.run(exercise())


def test_jellyfin_playlist_resource_overflow_fails_closed_without_partial_registration(
    tmp_path,
) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
            plan.resources.update(
                {
                    f"resource-{index}": HLSResource(f"https://jellyfin.test/used-{index}.ts")
                    for index in range(9_999)
                }
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

            assert response.status_code == 502
            assert response.json() == {"error": "Unsafe upstream playlist"}
            assert len(plan.resources) == 9_999
            assert "jellyfin.test" not in response.text
            assert TEST_JELLYFIN_ACCESS_TOKEN not in response.text

    asyncio.run(exercise())


def test_jellyfin_nested_playlist_is_fetched_by_registered_resource_id(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
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
