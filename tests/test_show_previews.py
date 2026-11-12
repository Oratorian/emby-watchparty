import asyncio
import logging
import secrets
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urljoin

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.dependencies import PartySession, require_party_unlocked
from backend.src.preview_manager import (
    PREVIEW_SECONDS,
    PreviewCapacityError,
    PreviewManager,
    PreviewUnavailableError,
)
from backend.src.providers.models import (
    HLSResource,
    MediaItem,
    MediaItemDetails,
    MediaPage,
    PlaybackMethod,
    PlaybackPlan,
    UnsafeProviderResourceError,
)
from backend.src.routers.previews import router
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN, TEST_SESSION_SECRET
from tests.support.fake_emby import FakeEmbyState, create_fake_emby_app
from tests.support.fake_jellyfin import FakeJellyfinState, create_fake_jellyfin_app


class PreviewProvider:
    def __init__(self):
        self.requests = []
        self.queries = []
        self.cancelled = []
        self.gate = None
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.on_prepare = None
        self.episode = MediaItem(
            id="episode-1",
            name="Episode",
            kind="episode",
            series_id="series-1",
            is_playable=True,
            runtime_seconds=600,
        )
        self.movie = MediaItemDetails(
            id="movie-1", name="Movie", kind="movie", is_playable=True, runtime_seconds=600
        )

    async def get_details(self, item_id, _credentials):
        if item_id == "movie-1":
            return self.movie
        if item_id == "series-1":
            return MediaItemDetails(id=item_id, name="Show", kind="series")
        return None

    async def query_catalog(self, query, _credentials):
        self.queries.append(query)
        return MediaPage(items=(self.episode,))

    async def prepare_playback(self, request):
        self.requests.append(request)
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.on_prepare:
            self.on_prepare()
        return PlaybackPlan(
            stream_id=f"stream-{len(self.requests)}",
            item_id=request.item_id,
            media_source_id="source-1",
            play_session_id=f"session-{len(self.requests)}",
            method=PlaybackMethod.HLS_TRANSCODE,
            master=HLSResource(
                f"http://media.test/Videos/{request.item_id}/master.m3u8?api_key=secret"
            ),
            credentials=request.credentials,
        )

    async def cancel_preview(self, plan):
        self.cancelled.append(plan.play_session_id)
        self.stopped.set()
        return True

    async def report_playback(self, _event):
        raise AssertionError("A preview must not report playback history")

    async def stop_playback(self, _event):
        raise AssertionError("A preview must not report stopped history")

    def resolve_hls_resource(self, plan, parent, uri):
        target = urljoin(parent.url, uri)
        if not target.startswith(f"http://media.test/Videos/{plan.item_id}/"):
            raise UnsafeProviderResourceError("Unapproved resource")
        return HLSResource(target)

    async def fetch_hls_resource(self, _plan, resource, *, range_header=None, head=False):
        del range_header
        content = (
            b"#EXTM3U\nmain.m3u8?api_key=secret\n"
            if "master.m3u8" in resource.url
            else b"#EXTM3U\n#EXTINF:6,\nsegment.ts?api_key=secret\n"
        )
        return httpx.Response(
            200,
            content=b"" if head else content,
            headers={"Content-Length": str(len(content))},
            request=httpx.Request("GET", resource.url),
        )

    async def open_hls_resource(self, _plan, resource, *, range_header=None):
        content = b"synthetic"
        status = 200
        headers = {"Content-Length": str(len(content)), "Accept-Ranges": "bytes"}
        if range_header == "bytes=0-2":
            status, content = 206, content[:3]
            headers.update({"Content-Length": "3", "Content-Range": "bytes 0-2/9"})
        elif range_header:
            status, content = 416, b""
            headers.update({"Content-Length": "0", "Content-Range": "bytes */9"})
        return httpx.Response(
            status, content=content, headers=headers, request=httpx.Request("GET", resource.url)
        )


def setup_manager(**kwargs):
    provider = PreviewProvider()
    party = SimpleNamespace(
        host_access_token=secrets.token_urlsafe(24),
        host_user_id="host-user",
        sid_client_ids={"sid-a": "a", "sid-b": "b"},
        playback_state=SimpleNamespace(playing=False),
        current_video=None,
        user_streams={},
    )
    other = SimpleNamespace(**vars(party))
    other.sid_client_ids = {"sid-c": "c"}
    parties = SimpleNamespace(
        get=lambda code: {"ROOM": party, "OTHER": other}.get(code), is_unlocked=lambda _code: True
    )
    manager = PreviewManager(provider, parties, logging.getLogger("test-show-preview"), **kwargs)
    return manager, provider, party


def test_preview_is_bounded_and_separate_from_party_playback():
    async def exercise():
        manager, provider, party = setup_manager()
        try:
            preview = await manager.create("ROOM", "a", "series-1")
            query = provider.queries[0]
            assert query.scope.parent_id == "series-1"
            assert query.scope.include_kinds == ("episode",)
            assert query.scope.recursive
            assert query.sort.field == "random"
            assert query.page.limit <= 8
            request = provider.requests[0]
            assert request.quality == "360p-750"
            assert request.force_transcode
            assert request.subtitle_index == -1
            assert request.client_codecs == frozenset({"h264"})
            assert 10 <= preview.start_seconds <= 600 - PREVIEW_SECONDS - 5
            assert party.current_video is None
            assert party.user_streams == {}
            assert not party.playback_state.playing
            assert manager.registry.get_plan(preview.preview_id) is preview.plan
        finally:
            await manager.close()
        assert provider.cancelled == ["session-1"]

    asyncio.run(exercise())


def test_movie_preview_uses_the_movie_without_an_episode_query():
    async def exercise():
        manager, provider, party = setup_manager()
        try:
            preview = await manager.create("ROOM", "a", "movie-1")
            assert provider.queries == []
            request = provider.requests[0]
            assert request.item_id == "movie-1"
            assert request.quality == "360p-750"
            assert request.force_transcode
            assert request.subtitle_index == -1
            assert 10 <= preview.start_seconds <= 600 - 120 - 5
            assert party.current_video is None
            assert party.user_streams == {}
            assert not party.playback_state.playing
        finally:
            await manager.close()
        assert provider.cancelled == ["session-1"]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_playable": False},
        {"is_folder": True},
        {"kind": "episode"},
        {"kind": "folder"},
        {"runtime_seconds": None},
        {"runtime_seconds": 134},
        {"runtime_seconds": float("nan")},
        {"runtime_seconds": float("inf")},
    ],
)
def test_unplayable_movie_previews_do_not_start_transcodes_or_query_episodes(overrides):
    async def exercise():
        manager, provider, _party = setup_manager()
        provider.movie = replace(provider.movie, **overrides)
        try:
            with pytest.raises(PreviewUnavailableError):
                await manager.create("ROOM", "a", "movie-1")
            assert provider.queries == []
            assert provider.requests == []
            assert not manager._records
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_shortest_supported_movie_keeps_the_full_clip_inside_its_runtime():
    async def exercise():
        manager, provider, _party = setup_manager()
        provider.movie = replace(provider.movie, runtime_seconds=135)
        try:
            preview = await manager.create("ROOM", "a", "movie-1")
            assert preview.start_seconds == 10
            assert provider.requests[0].start_seconds + 120 <= 135 - 5
            assert not provider.queries
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_replacement_stops_only_the_previous_preview():
    async def exercise():
        manager, provider, _party = setup_manager()
        try:
            first = await manager.create("ROOM", "a", "series-1")
            second = await manager.create("ROOM", "a", "series-1")
            assert provider.cancelled == ["session-1"]
            assert manager.registry.get_plan(first.preview_id) is None
            assert await manager.authorize(second.preview_id, "ROOM", "a", second.token) is second
            assert await manager.authorize(second.preview_id, "ROOM", "b", second.token) is None
            assert await manager.authorize(second.preview_id, "OTHER", "c", second.token) is None
            assert await manager.authorize(second.preview_id, "ROOM", "a", "wrong") is None
            assert not await manager.stop(second.preview_id, "ROOM", "b")
        finally:
            await manager.close()
        assert provider.cancelled == ["session-1", "session-2"]

    asyncio.run(exercise())


def test_capacity_is_released_after_stop():
    async def exercise():
        manager, provider, _party = setup_manager(capacity=1)
        try:
            first = await manager.create("ROOM", "a", "series-1")
            with pytest.raises(PreviewCapacityError):
                await manager.create("ROOM", "b", "series-1")
            assert len(provider.requests) == 1
            await manager.stop(first.preview_id, "ROOM", "a")
            await manager.create("ROOM", "b", "series-1")
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_expiry_stops_abandoned_preview_without_history_reports():
    async def exercise():
        manager, provider, _party = setup_manager(ttl=0.01)
        preview = await manager.create("ROOM", "a", "series-1")
        await asyncio.wait_for(provider.stopped.wait(), timeout=1)
        assert provider.cancelled == ["session-1"]
        assert manager.registry.get_plan(preview.preview_id) is None
        await manager.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("reason", ["host_changed", "viewer_left", "party_playing"])
def test_authorization_invalidates_changed_session(reason):
    async def exercise():
        manager, provider, party = setup_manager()
        try:
            preview = await manager.create("ROOM", "a", "series-1")
            if reason == "host_changed":
                party.host_access_token = secrets.token_urlsafe(24)
            elif reason == "viewer_left":
                party.sid_client_ids.pop("sid-a")
            else:
                party.playback_state.playing = True
            assert await manager.authorize(preview.preview_id, "ROOM", "a", preview.token) is None
            assert provider.cancelled == ["session-1"]
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_preparation_cancel_and_host_race_do_not_install_or_leak_plans():
    async def exercise():
        manager, provider, party = setup_manager()
        try:
            provider.gate = asyncio.Event()
            pending = asyncio.create_task(manager.create("ROOM", "a", "series-1"))
            await provider.started.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert not manager._records
            provider.gate = None
            provider.on_prepare = lambda: setattr(party, "host_access_token", "replaced-host")
            with pytest.raises(PreviewUnavailableError):
                await manager.create("ROOM", "a", "series-1")
            assert provider.cancelled == ["session-2"]
            assert not manager._records
        finally:
            await manager.close()

    asyncio.run(exercise())


def preview_app():
    manager, provider, party = setup_manager()
    app = FastAPI()
    app.include_router(router)
    app.state.preview_manager = manager
    app.state.media_server = provider
    app.state.config = SimpleNamespace(APP_PREFIX="")
    app.state.logger = logging.getLogger("test-show-preview")

    async def session(request: Request):
        owner = request.headers.get("x-test-owner")
        if owner not in {"a", "b", "c"}:
            raise HTTPException(401, "No party session")
        return PartySession("OTHER" if owner == "c" else "ROOM", owner, owner, None, party)

    app.dependency_overrides[require_party_unlocked] = session
    return app, manager, provider


def test_preview_routes_auth_opaque_urls_head_and_ranges():
    async def exercise():
        app, manager, provider = preview_app()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                assert (await client.post("/api/v2/items/series-1/preview")).status_code == 401
                created = await client.post(
                    "/api/v2/items/series-1/preview", headers={"x-test-owner": "a"}
                )
                assert created.status_code == 201
                data = created.json()
                assert data["duration_seconds"] == 120
                assert data["expires_in"] == 180
                master = await client.get(data["url"], headers={"x-test-owner": "a"})
                assert master.status_code == 200
                assert "media.test" not in master.text
                assert "secret" not in master.text
                assert "/api/v2/previews/" in master.text
                assert "/hls/" not in master.text
                for other in ("b", "c"):
                    assert (
                        await client.get(data["url"], headers={"x-test-owner": other})
                    ).status_code == 404
                assert (
                    await client.get(data["url"].split("?")[0], headers={"x-test-owner": "a"})
                ).status_code == 422
                head = await client.head(data["url"], headers={"x-test-owner": "a"})
                assert head.status_code == 200
                assert not head.content
                variant_url = next(
                    line for line in master.text.splitlines() if line and not line.startswith("#")
                )
                variant = await client.get(variant_url, headers={"x-test-owner": "a"})
                segment_url = next(
                    line for line in variant.text.splitlines() if line and not line.startswith("#")
                )
                ranged = await client.get(
                    segment_url, headers={"x-test-owner": "a", "Range": "bytes=0-2"}
                )
                assert ranged.status_code == 206
                assert ranged.content == b"syn"
                assert ranged.headers["content-range"] == "bytes 0-2/9"
                invalid = await client.get(
                    segment_url, headers={"x-test-owner": "a", "Range": "bytes=999-"}
                )
                assert invalid.status_code == 416
                assert invalid.headers["content-range"] == "bytes */9"
                assert (
                    await client.delete(
                        f"/api/v2/previews/{data['preview_id']}", headers={"x-test-owner": "b"}
                    )
                ).status_code == 204
                assert not provider.cancelled
                assert (
                    await client.delete(
                        f"/api/v2/previews/{data['preview_id']}", headers={"x-test-owner": "a"}
                    )
                ).status_code == 204
                assert provider.cancelled == ["session-1"]
                assert (
                    await client.get(data["url"], headers={"x-test-owner": "a"})
                ).status_code == 404
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_disconnected_create_is_cleaned_up(monkeypatch):
    async def disconnected(_request):
        return True

    monkeypatch.setattr(Request, "is_disconnected", disconnected)

    async def exercise():
        app, manager, provider = preview_app()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                result = await client.post(
                    "/api/v2/items/series-1/preview", headers={"x-test-owner": "a"}
                )
                assert result.status_code == 404
                assert provider.cancelled == ["session-1"]
                assert not manager._records
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_unsafe_playlist_is_curated_and_cancels_the_preview():
    async def exercise():
        app, manager, provider = preview_app()
        provider.fetch_hls_resource = AsyncMock(
            return_value=httpx.Response(
                200,
                text="#EXTM3U\nhttps://unapproved.test/segment.ts?api_key=secret\n",
                request=httpx.Request("GET", "http://media.test/master.m3u8"),
            )
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                created = await client.post(
                    "/api/v2/items/series-1/preview", headers={"x-test-owner": "a"}
                )
                preview = created.json()
                response = await client.get(preview["url"], headers={"x-test-owner": "a"})
                assert response.status_code == 502
                assert response.json() == {"detail": "Preview unavailable"}
                assert provider.cancelled == ["session-1"]
                assert manager.registry.get_plan(preview["preview_id"]) is None
        finally:
            await manager.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["fetch", "open"])
def test_revocation_waits_for_late_upstream_requests_before_final_encoding_stop(phase):
    async def exercise():
        app, manager, provider = preview_app()
        events = []
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()

        class TrackedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"late resource must not be returned"

            async def aclose(self):
                events.append("response_closed")

        async def late_request(*_args, **_kwargs):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Deliberately model an upstream transport which finishes its
                # request despite cancellation, starting an encoding late.
                cancelled.set()
                await release.wait()
            events.append("late_request_completed")
            return httpx.Response(
                200, stream=TrackedStream(), request=httpx.Request("GET", "http://media.test/late")
            )

        original_cancel = provider.cancel_preview

        async def cancel_encoding(plan):
            events.append("encoding_cancelled")
            return await original_cancel(plan)

        provider.cancel_preview = cancel_encoding
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                created = await client.post(
                    "/api/v2/items/series-1/preview", headers={"x-test-owner": "a"}
                )
                preview = created.json()
                url = preview["url"]
                if phase == "open":
                    master = await client.get(url, headers={"x-test-owner": "a"})
                    variant_url = next(
                        line for line in master.text.splitlines() if not line.startswith("#")
                    )
                    variant = await client.get(variant_url, headers={"x-test-owner": "a"})
                    url = next(
                        line for line in variant.text.splitlines() if not line.startswith("#")
                    )
                    provider.open_hls_resource = late_request
                else:
                    provider.fetch_hls_resource = late_request
                reading = asyncio.create_task(client.get(url, headers={"x-test-owner": "a"}))
                await asyncio.wait_for(started.wait(), 1)
                stopping = asyncio.create_task(
                    client.delete(
                        f"/api/v2/previews/{preview['preview_id']}", headers={"x-test-owner": "a"}
                    )
                )
                await asyncio.wait_for(cancelled.wait(), 1)
                assert provider.cancelled == []
                release.set()
                response = await asyncio.wait_for(reading, 2)
                stopped = await asyncio.wait_for(stopping, 2)
                assert stopped.status_code == 204
                assert response.status_code == 404
                assert b"late resource" not in response.content
                assert events == ["late_request_completed", "response_closed", "encoding_cancelled"]
                assert provider.cancelled == ["session-1"]
                assert manager.registry.get_plan(preview["preview_id"]) is None
        finally:
            release.set()
            await manager.close()

    asyncio.run(exercise())


def test_transport_cancellation_releases_the_preview():
    async def exercise():
        manager, provider, _party = setup_manager()
        preview = await manager.create("ROOM", "a", "series-1")
        started = asyncio.Event()

        async def pending_request():
            started.set()
            await asyncio.Event().wait()

        reading = asyncio.create_task(manager.run_request(preview, pending_request))
        await started.wait()
        reading.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reading
        assert provider.cancelled == ["session-1"]
        assert not preview.requests
        assert manager.registry.get_plan(preview.preview_id) is None
        await manager.close()

    asyncio.run(exercise())


def test_stop_closes_an_open_stream_before_cancelling_its_encoding():
    async def exercise():
        manager, provider, _party = setup_manager()
        preview = await manager.create("ROOM", "a", "series-1")
        events = []

        class OpenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"video"

            async def aclose(self):
                events.append("closed")

        async def open_stream():
            return httpx.Response(200, stream=OpenStream())

        async def cancel_encoding(_plan):
            events.append("cancelled")
            return True

        provider.cancel_preview = cancel_encoding
        response = await manager.run_request(preview, open_stream)
        assert not response.is_closed
        await manager.stop(preview.preview_id, "ROOM", "a")
        assert response.is_closed
        assert events == ["closed", "cancelled"]
        assert not preview.responses
        await manager.close()

    asyncio.run(exercise())


def test_preview_openapi_has_binary_contracts_and_unique_operation_ids():
    app, _manager, _provider = preview_app()
    schema = app.openapi()
    operations = [operation for path in schema["paths"].values() for operation in path.values()]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids))
    resource = schema["paths"]["/api/v2/previews/{preview_id}/resources/{resource_id}"]
    assert "video/MP2T" in resource["get"]["responses"]["200"]["content"]
    assert "206" in resource["get"]["responses"]
    assert "416" in resource["get"]["responses"]
    assert "content" not in resource["head"]["responses"]["200"]
    assert "content" not in resource["head"]["responses"]["429"]


@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
@pytest.mark.parametrize("media_kind", ["series", "movie"])
def test_real_provider_preview_lifecycle_does_not_touch_party_or_watch_history(
    tmp_path, kind, media_kind
):
    state = FakeEmbyState() if kind == "emby" else FakeJellyfinState()
    fake = create_fake_emby_app(state) if kind == "emby" else create_fake_jellyfin_app(state)
    if kind == "jellyfin":

        @fake.delete("/Videos/ActiveEncodings")
        async def stop_encoding(request: Request):
            state.record(request)
            return Response(status_code=204)

    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE=kind,
            MEDIA_SERVER_URL="http://media.test",
            MEDIA_SERVER_API_KEY=TEST_JELLYFIN_ACCESS_TOKEN,
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=True,
        ),
        RuntimeConfig(LOG_TO_FILE=False, ENABLE_RATE_LIMITING=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=fake),
    )

    async def exercise():
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create", json={"client_id": "a", "display_name": "Alice"}
            )
            party_id = created.json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join", json={"client_id": "a", "display_name": "Alice"}
            )
            logged_in = await client.post(
                "/api/v2/auth/login", json={"username": "PreviewViewer", "password": "password"}
            )
            assert logged_in.status_code == 200
            party = app.state.party_manager.get(party_id)
            party.sid_client_ids["sid-a"] = "a"
            provider = app.state.media_server
            item_id = "movie-1" if media_kind == "movie" else "series-1"
            provider.get_details = AsyncMock(
                return_value=MediaItemDetails(
                    id=item_id,
                    name="Title",
                    kind=media_kind,
                    is_playable=media_kind == "movie",
                    runtime_seconds=600,
                )
            )
            provider.query_catalog = AsyncMock(
                return_value=MediaPage(
                    items=(
                        MediaItem(
                            id="episode-1",
                            name="Episode",
                            kind="episode",
                            is_playable=True,
                            runtime_seconds=600,
                            series_id="series-1",
                        ),
                    )
                )
            )
            preview = await client.post(f"/api/v2/items/{item_id}/preview")
            assert preview.status_code == 201, preview.text
            if media_kind == "movie":
                provider.query_catalog.assert_not_awaited()
            else:
                provider.query_catalog.assert_awaited_once()
            data = preview.json()
            master = await client.get(data["url"])
            assert master.status_code == 200, master.text
            assert "media.test" not in master.text
            assert TEST_JELLYFIN_ACCESS_TOKEN not in master.text
            variant_url = next(
                line for line in master.text.splitlines() if line and not line.startswith("#")
            )
            variant = await client.get(variant_url)
            assert variant.status_code == 200, variant.text
            assert party.current_video is None
            assert party.user_streams == {}
            stopped = await client.delete(f"/api/v2/previews/{data['preview_id']}")
            assert stopped.status_code == 204
            assert app.state.preview_manager.registry.get_plan(data["preview_id"]) is None
            assert not any("/Sessions/Playing" in row["path"] for row in state.requests)
            assert any(
                row["method"] == "DELETE" and row["path"].endswith("/Videos/ActiveEncodings")
                for row in state.requests
            )

    asyncio.run(exercise())
