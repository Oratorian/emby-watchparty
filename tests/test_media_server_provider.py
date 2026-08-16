import asyncio
import logging

import httpx
import pytest

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.domain import SelectedMedia
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers import EmbyProvider, JellyfinProvider, create_provider
from backend.src.providers.models import (
    HLSResource,
    PlaybackEvent,
    PlaybackEventType,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackRequest,
    ProviderCredentials,
    UnsafeProviderResourceError,
)
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN
from tests.support.fake_jellyfin import FakeJellyfinState, create_fake_jellyfin_app


def _config(provider: str) -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="emby-key",
            APP_ENV="development",
            SESSION_SECRET="",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            MEDIA_SERVER_TYPE=provider,
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY="jellyfin-key",
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def test_factory_selects_emby_adapter_without_changing_client_surface() -> None:
    config = _config("emby")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))

    provider = create_provider(config, logging.getLogger("test"), gateway)

    assert isinstance(provider, EmbyProvider)
    assert provider.identity.type == "emby"
    assert provider.server_url == "http://emby.test"
    assert provider.get_libraries is not None


def test_factory_selects_jellyfin_adapter() -> None:
    config = _config("jellyfin")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))

    provider = create_provider(config, logging.getLogger("test"), gateway)

    assert isinstance(provider, JellyfinProvider)
    assert provider.identity.type == "jellyfin"
    assert provider.server_url == "http://jellyfin.test"


def test_app_lifespan_installs_selected_provider(tmp_path) -> None:
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.media_server.identity.type == "jellyfin"
            assert app.state.emby_client is app.state.media_server
            assert app.state.socket_context["media_server"] is app.state.media_server

    asyncio.run(exercise())


def test_jellyfin_user_can_authenticate_and_browse_v2_library(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    fake = create_fake_jellyfin_app(fake_state)
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=fake),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            party_id = created.json()["party_id"]
            joined = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            assert joined.status_code == 200

            login = await client.post(
                "/api/v2/auth/login",
                json={"username": "Alice", "password": "secret"},
            )
            assert login.status_code == 200
            assert login.json()["media_server_type"] == "jellyfin"
            assert login.json()["success"] is True

            libraries = await client.get("/api/v2/libraries")
            assert libraries.status_code == 200
            assert libraries.json() == {
                "items": [
                    {
                        "id": "jellyfin-library-1",
                        "name": "Movies",
                        "kind": "collection_folder",
                        "collection_kind": "movies",
                        "overview": "",
                        "runtime_seconds": None,
                        "production_year": None,
                        "parent_id": None,
                        "series_id": None,
                        "series_name": None,
                        "season_id": None,
                        "season_name": None,
                        "index_number": None,
                        "parent_index_number": None,
                        "is_folder": True,
                        "is_playable": False,
                        "is_browsable": True,
                        "has_primary_image": True,
                        "backdrop_count": 0,
                        "primary_image_aspect_ratio": None,
                        "user_state": {
                            "playback_position_seconds": 0.0,
                            "played_percentage": None,
                            "played": False,
                            "favorite": False,
                        },
                        "media_source_count": 0,
                    }
                ],
                "total": 1,
                "start": 0,
            }

    asyncio.run(exercise())
    assert all(not request["path"].startswith("/emby/") for request in fake_state.requests)


def test_jellyfin_v2_item_query_is_normalized_and_user_scoped(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.post(
                "/api/v2/items/query",
                json={
                    "scope": {
                        "parent_id": "jellyfin-library-1",
                        "include_kinds": ["movie"],
                        "recursive": True,
                    },
                    "page": {"start": 20, "limit": 25},
                    "sort": {"field": "name", "direction": "ascending"},
                    "filters": {"favorite": True},
                },
            )

            assert response.status_code == 200
            assert response.json()["items"] == [
                {
                    "id": "movie-1",
                    "name": "Arrival",
                    "kind": "movie",
                    "collection_kind": None,
                    "overview": "",
                    "runtime_seconds": 696.0,
                    "production_year": 2016,
                    "parent_id": None,
                    "series_id": None,
                    "series_name": None,
                    "season_id": None,
                    "season_name": None,
                    "index_number": None,
                    "parent_index_number": None,
                    "is_folder": False,
                    "is_playable": True,
                    "is_browsable": False,
                    "has_primary_image": True,
                    "backdrop_count": 0,
                    "primary_image_aspect_ratio": None,
                    "user_state": {
                        "playback_position_seconds": 0.0,
                        "played_percentage": None,
                        "played": False,
                        "favorite": True,
                    },
                    "media_source_count": 1,
                }
            ]
            assert response.json()["start"] == 20

    asyncio.run(exercise())
    item_request = next(row for row in fake_state.requests if row["path"].endswith("/Items"))
    assert item_request == {
        "method": "GET",
        "path": "/Users/jellyfin-user-1/Items",
        "query": {
            "Recursive": "true",
            "Fields": (
                "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,"
                "ParentIndexNumber,SeriesId,SeasonId,UserData,MediaSourceCount"
            ),
            "SortBy": "SortName",
            "SortOrder": "Ascending",
            "StartIndex": "20",
            "Limit": "25",
            "ParentId": "jellyfin-library-1",
            "IncludeItemTypes": "Movie",
            "IsFavorite": "true",
        },
    }


def test_jellyfin_v2_item_details_do_not_leak_provider_json(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.get("/api/v2/items/movie-1")

            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == "movie-1"
            assert payload["name"] == "Arrival"
            assert payload["kind"] == "movie"
            assert payload["runtime_seconds"] == 696.0
            assert payload["genres"] == ["Drama", "Science Fiction"]
            assert payload["tags"] == ["First contact"]
            assert payload["people"] == [{"id": "person-1", "name": "Amy Adams", "kind": "actor"}]
            assert payload["studios"] == ["Paramount"]
            assert payload["official_rating"] == "PG-13"
            assert payload["community_rating"] == 7.9
            assert payload["critic_rating"] == 94.0
            assert "Id" not in payload
            assert "MediaSources" not in payload

    asyncio.run(exercise())
    detail_request = next(
        row for row in fake_state.requests if row["path"] == "/Users/jellyfin-user-1/Items/movie-1"
    )
    assert detail_request["query"] == {"api_key": "<redacted>"}


def test_jellyfin_posted_playback_info_becomes_hls_plan(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app):
            plan = await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                    media_source_id="source-1",
                    audio_index=2,
                    subtitle_index=4,
                    quality="720p-4000",
                    start_seconds=12.5,
                    client_codecs=frozenset({"h264", "hevc"}),
                )
            )

            assert plan.item_id == "movie-1"
            assert plan.media_source_id == "source-1"
            assert plan.play_session_id == "jellyfin-play-session-1"
            assert plan.method is PlaybackMethod.HLS_TRANSCODE
            assert plan.master.url == (
                "http://jellyfin.test/Videos/movie-1/master.m3u8?MediaSourceId=source-1&"
                f"PlaySessionId=jellyfin-play-session-1&api_key={TEST_JELLYFIN_ACCESS_TOKEN}"
            )
            assert TEST_JELLYFIN_ACCESS_TOKEN not in repr(plan)

    asyncio.run(exercise())
    assert len(fake_state.playback_requests) == 1
    request = fake_state.playback_requests[0]
    assert request["UserId"] == "jellyfin-user-1"
    assert request["MediaSourceId"] == "source-1"
    assert request["StartTimeTicks"] == 125_000_000
    assert request["AudioStreamIndex"] == 2
    assert request["SubtitleStreamIndex"] == 4
    assert request["MaxStreamingBitrate"] == 4_000_000
    assert request["EnableDirectPlay"] is False
    assert request["EnableDirectStream"] is True
    assert request["EnableTranscoding"] is True
    assert request["AllowVideoStreamCopy"] is True
    profile = request["DeviceProfile"]
    assert profile["Name"] == "Emby Watch Party HLS"
    assert profile["TranscodingProfiles"][0]["Protocol"] == "hls"
    assert profile["TranscodingProfiles"][0]["Container"] == "ts"


def test_jellyfin_hls_children_are_same_origin_and_item_scoped(tmp_path) -> None:
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )

    async def exercise() -> None:
        async with asgi_client(app):
            provider = app.state.media_server
            plan = await provider.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                )
            )
            child = provider.resolve_hls_resource(plan, plan.master, "nested/MAIN.M3U8?part=1")
            assert child.url == ("http://jellyfin.test/Videos/movie-1/nested/MAIN.M3U8?part=1")

            for unsafe in (
                "https://foreign.test/steal.ts",
                "/Videos/other-item/segment.ts",
                "nested/%252e%252e/secret.ts",
                "nested\\..\\secret.ts",
            ):
                with pytest.raises(UnsafeProviderResourceError):
                    provider.resolve_hls_resource(plan, plan.master, unsafe)

    asyncio.run(exercise())


def test_jellyfin_reports_complete_playback_lifecycle(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )
    credentials = ProviderCredentials(
        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
        user_id="jellyfin-user-1",
    )

    async def exercise() -> None:
        async with asgi_client(app):
            provider = app.state.media_server
            for event_type, position, paused in (
                (PlaybackEventType.START, 12.5, False),
                (PlaybackEventType.PROGRESS, 18.0, True),
                (PlaybackEventType.STOP, 21.25, False),
            ):
                event = PlaybackEvent(
                    type=event_type,
                    item_id="movie-1",
                    media_source_id="source-1",
                    play_session_id="session-1",
                    position_seconds=position,
                    credentials=credentials,
                    is_paused=paused,
                )
                if event_type is PlaybackEventType.STOP:
                    assert await provider.stop_playback(event)
                else:
                    assert await provider.report_playback(event)

    asyncio.run(exercise())
    assert [report["path"] for report in fake_state.playback_reports] == [
        "/Sessions/Playing",
        "/Sessions/Playing/Progress",
        "/Sessions/Playing/Stopped",
    ]
    assert [report["body"]["PositionTicks"] for report in fake_state.playback_reports] == [
        125_000_000,
        180_000_000,
        212_500_000,
    ]
    assert all(
        report["body"]["ItemId"] == "movie-1"
        and report["body"]["MediaSourceId"] == "source-1"
        and report["body"]["PlaySessionId"] == "session-1"
        for report in fake_state.playback_reports
    )
    assert fake_state.playback_reports[1]["body"]["IsPaused"] is True


def test_socket_creates_registered_per_viewer_jellyfin_plan(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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
            party.current_video = SelectedMedia(item_id="movie-1", title="Arrival")
            party.client_codecs["client-1"] = {"h264", "hevc"}

            stream = await app.state.socket_context["create_user_stream"](
                party,
                party_id,
                sid,
                "movie-1",
                None,
                2,
                4,
                "720p-4000",
                start_seconds=12.5,
                media_source_id="source-1",
            )

            assert stream is not None
            assert stream.stream_id
            assert stream.stream_url_base == f"/hls/{stream.stream_id}/master.m3u8"
            assert TEST_JELLYFIN_ACCESS_TOKEN not in stream.stream_url_base
            plan = app.state.hls_registry.get_plan(stream.stream_id)
            assert plan is not None
            assert plan.play_session_id == stream.play_session_id
            assert plan.media_source_id == stream.media_source_id
            assert party.user_streams[sid] is stream

            await app.state.socket_context["stop_user_stream"](party, sid, 14.0)

            assert sid not in party.user_streams
            assert app.state.hls_registry.get_plan(stream.stream_id) is None

    asyncio.run(exercise())
    assert [report["path"] for report in fake_state.playback_reports] == [
        "/Sessions/Playing",
        "/Sessions/Playing/Stopped",
    ]


def test_jellyfin_v2_search_is_normalized_and_bounded(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.get("/api/v2/items/search?q=Arrival&limit=7")

            assert response.status_code == 200
            assert [
                (item["id"], item["name"], item["kind"]) for item in response.json()["items"]
            ] == [("movie-1", "Arrival", "movie")]

    asyncio.run(exercise())
    request = next(
        row
        for row in fake_state.requests
        if row["path"] == "/Users/jellyfin-user-1/Items"
        and row["query"].get("SearchTerm") == "Arrival"
    )
    assert request["query"]["Recursive"] == "true"
    assert request["query"]["Limit"] == "7"
    assert request["query"]["IncludeItemTypes"] == "Movie,Series,Episode,Person,BoxSet"


def test_jellyfin_v2_series_seasons_are_normalized(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.get("/api/v2/items/series-1/seasons")

            assert response.status_code == 200
            assert [
                (item["id"], item["kind"], item["series_id"]) for item in response.json()["items"]
            ] == [("season-1", "season", "series-1")]

    asyncio.run(exercise())
    request = next(row for row in fake_state.requests if row["path"] == "/Shows/series-1/Seasons")
    assert request["query"] == {"UserId": "jellyfin-user-1"}


def test_jellyfin_v2_series_episodes_are_season_scoped_and_normalized(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.get("/api/v2/items/series-1/episodes?season_id=season-1")

            assert response.status_code == 200
            episode = response.json()["items"][0]
            assert episode["id"] == "episode-1"
            assert episode["kind"] == "episode"
            assert episode["series_id"] == "series-1"
            assert episode["season_id"] == "season-1"
            assert episode["index_number"] == 1
            assert episode["runtime_seconds"] == 240.0

    asyncio.run(exercise())
    request = next(row for row in fake_state.requests if row["path"] == "/Shows/series-1/Episodes")
    assert request["query"] == {
        "UserId": "jellyfin-user-1",
        "SeasonId": "season-1",
    }


def test_jellyfin_v2_host_updates_favorite_and_played_state(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            favorite = await client.put("/api/v2/items/movie-1/favorite", json={"favorite": True})
            played = await client.put("/api/v2/items/movie-1/played", json={"played": True})

            assert favorite.status_code == 200
            assert favorite.json() == {"success": True, "favorite": True}
            assert played.status_code == 200
            assert played.json() == {"success": True, "played": True}

    asyncio.run(exercise())
    mutations = [
        (row["method"], row["path"])
        for row in fake_state.requests
        if "FavoriteItems" in row["path"] or "PlayedItems" in row["path"]
    ]
    assert mutations == [
        ("POST", "/Users/jellyfin-user-1/FavoriteItems/movie-1"),
        ("POST", "/Users/jellyfin-user-1/PlayedItems/movie-1"),
    ]


def test_jellyfin_v2_host_lists_normalized_playlists(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.get("/api/v2/playlists")

            assert response.status_code == 200
            assert response.json() == {
                "items": [
                    {
                        "id": "playlist-1",
                        "name": "Movie Night",
                        "kind": "playlist",
                        "collection_kind": None,
                        "overview": "",
                        "runtime_seconds": None,
                        "production_year": None,
                        "parent_id": None,
                        "series_id": None,
                        "series_name": None,
                        "season_id": None,
                        "season_name": None,
                        "index_number": None,
                        "parent_index_number": None,
                        "is_folder": True,
                        "is_playable": False,
                        "is_browsable": True,
                        "has_primary_image": False,
                        "backdrop_count": 0,
                        "primary_image_aspect_ratio": None,
                        "user_state": {
                            "playback_position_seconds": 0.0,
                            "played_percentage": None,
                            "played": False,
                            "favorite": False,
                        },
                        "media_source_count": 0,
                    }
                ],
                "total": 1,
                "start": 0,
            }

    asyncio.run(exercise())
    request = next(
        row
        for row in fake_state.requests
        if row["path"] == "/Users/jellyfin-user-1/Items"
        and row["query"].get("IncludeItemTypes") == "Playlist"
    )
    assert request["query"] == {"Recursive": "true", "IncludeItemTypes": "Playlist"}


def test_jellyfin_v2_host_creates_playlist(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.post("/api/v2/playlists", json={"name": "Friday Night"})

            assert response.status_code == 201
            assert response.json() == {"id": "playlist-created", "name": "Friday Night"}

    asyncio.run(exercise())
    request = next(row for row in fake_state.requests if row["path"] == "/Playlists")
    assert request["method"] == "POST"
    assert request["query"] == {"Name": "Friday Night", "UserId": "jellyfin-user-1"}


def test_jellyfin_v2_host_adds_item_to_playlist(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            response = await client.post(
                "/api/v2/playlists/playlist-1/items", json={"item_id": "movie-1"}
            )

            assert response.status_code == 200
            assert response.json() == {"success": True}

    asyncio.run(exercise())
    request = next(
        row for row in fake_state.requests if row["path"] == "/Playlists/playlist-1/Items"
    )
    assert request["method"] == "POST"
    assert request["query"] == {"Ids": "movie-1", "UserId": "jellyfin-user-1"}


def test_jellyfin_provider_streams_approved_hls_resource_and_closes_upstream() -> None:
    class TrackingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b"segment-"
            yield b"bytes"

        async def aclose(self) -> None:
            self.closed = True

    tracking_stream = TrackingStream()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            206,
            headers={"Content-Range": "bytes 2-14/15"},
            stream=tracking_stream,
        )

    async def exercise() -> None:
        config = _config("jellyfin")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))
        provider = create_provider(config, logging.getLogger("test"), gateway)
        resource = HLSResource("http://jellyfin.test/Videos/movie-1/segment0001.ts")
        plan = PlaybackPlan(
            stream_id="stream-1",
            item_id="movie-1",
            media_source_id="source-1",
            play_session_id="play-session-1",
            method=PlaybackMethod.HLS_TRANSCODE,
            master=HLSResource("http://jellyfin.test/Videos/movie-1/master.m3u8"),
            credentials=ProviderCredentials(TEST_JELLYFIN_ACCESS_TOKEN, "jellyfin-user-1"),
            resources={"resource-1": resource},
        )

        response = await provider.open_hls_resource(plan, resource, range_header="bytes=2-14")

        assert response.is_stream_consumed is False
        assert tracking_stream.closed is False
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == b"segment-bytes"
        await response.aclose()
        await client.aclose()

    asyncio.run(exercise())
    assert tracking_stream.closed is True
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].headers["range"] == "bytes=2-14"
    assert requests[0].headers["x-emby-token"] == TEST_JELLYFIN_ACCESS_TOKEN


def test_jellyfin_v2_auth_status_and_logout_are_provider_aware(tmp_path) -> None:
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
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

            status = await client.get("/api/v2/auth/status")
            logout = await client.post("/api/v2/auth/logout")
            logged_out = await client.get("/api/v2/auth/status")

            assert status.status_code == 200
            assert status.json() == {
                "authenticated": True,
                "username": "Alice",
                "is_admin": True,
                "require_login": False,
                "is_host": True,
                "party_id": party_id,
                "host_username": "Alice",
                "party_unlocked": True,
                "media_server_type": "jellyfin",
            }
            assert logout.status_code == 200
            assert logout.json() == {"success": True, "message": "Logged out"}
            assert logged_out.json()["authenticated"] is False
            assert logged_out.json()["media_server_type"] == "jellyfin"

    asyncio.run(exercise())


def test_jellyfin_item_artwork_is_available_through_v1_and_v2(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            legacy = await client.get(
                "/api/image/movie-1",
                params={"type": "Backdrop", "index": 1, "maxWidth": 640},
            )
            neutral = await client.get(
                "/api/v2/items/movie-1/images/backdrop",
                params={"index": 1, "max_width": 640},
            )

            for response in (legacy, neutral):
                assert response.status_code == 200
                assert response.content == b"jellyfin-image"
                assert response.headers["content-type"].startswith("image/png")
                assert response.headers["x-content-type-options"] == "nosniff"

    asyncio.run(exercise())
    images = [row for row in fake_state.requests if "/Images/" in row["path"]]
    assert [row["path"] for row in images] == [
        "/Items/movie-1/Images/Backdrop/1",
        "/Items/movie-1/Images/Backdrop/1",
    ]
    assert all(row["query"] == {"maxWidth": "640"} for row in images)


def test_jellyfin_subtitles_are_available_through_v1_and_v2(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            legacy = await client.get("/api/subtitles/movie-1/source-1/4")
            neutral = await client.get(
                "/api/v2/items/movie-1/subtitles/source-1/4",
            )

            for response in (legacy, neutral):
                assert response.status_code == 200
                assert response.text.startswith("WEBVTT")
                assert response.headers["content-type"].startswith("text/vtt")
                assert response.headers["x-content-type-options"] == "nosniff"

    asyncio.run(exercise())
    subtitles = [row for row in fake_state.requests if "/Subtitles/" in row["path"]]
    assert [row["path"] for row in subtitles] == [
        "/Videos/movie-1/source-1/Subtitles/4/Stream.vtt",
        "/Videos/movie-1/source-1/Subtitles/4/Stream.vtt",
    ]
    assert all(row["query"] == {} for row in subtitles)


def test_jellyfin_intro_segment_is_available_through_v1_and_v2(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
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

            legacy = await client.get("/api/intro/movie-1")
            neutral = await client.get("/api/v2/items/movie-1/intro")

            assert legacy.json() == {
                "hasIntro": True,
                "start": 2.5,
                "end": 92.5,
                "duration": 90.0,
            }
            assert neutral.json() == {
                "has_intro": True,
                "start_seconds": 2.5,
                "end_seconds": 92.5,
                "duration_seconds": 90.0,
            }

    asyncio.run(exercise())
    segments = [row for row in fake_state.requests if row["path"] == "/MediaSegments/movie-1"]
    assert len(segments) == 2
    assert all(row["query"] == {} for row in segments)


def test_jellyfin_v2_streams_and_versions_are_normalized(tmp_path) -> None:
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
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

            response = await client.get(
                "/api/v2/items/movie-1/streams",
                params={"media_source_id": "source-2"},
            )

            assert response.status_code == 200
            assert response.json() == {
                "audio": [
                    {
                        "index": 1,
                        "language": "eng",
                        "display_language": "English Stereo",
                        "codec": "aac",
                        "channels": 2,
                        "is_default": True,
                        "title": "Main",
                    }
                ],
                "subtitles": [
                    {
                        "index": 4,
                        "language": "spa",
                        "display_language": "Spanish",
                        "codec": "srt",
                        "is_default": False,
                        "is_forced": False,
                        "is_external": True,
                        "is_text": True,
                        "is_image": False,
                        "title": "",
                    }
                ],
                "media_source_id": "source-2",
                "versions": [
                    {
                        "id": "source-1",
                        "name": "1080p",
                        "container": "mkv",
                        "runtime_seconds": 696.0,
                    },
                    {
                        "id": "source-2",
                        "name": "4K",
                        "container": "mkv",
                        "runtime_seconds": 696.0,
                    },
                ],
            }

    asyncio.run(exercise())
