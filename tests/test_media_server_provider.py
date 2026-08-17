import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.dependencies import get_media_server
from backend.src.domain import Participant, SelectedMedia
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers import EmbyProvider, JellyfinProvider, create_provider
from backend.src.providers.jellyfin import _subtitle_must_be_burned_in
from backend.src.providers.models import (
    AuthenticatedUser,
    HLSResource,
    PlaybackEvent,
    PlaybackEventType,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackRequest,
    ProviderCredentials,
    ProviderIdentity,
    UnsafeProviderResourceError,
)
from tests.support.asgi import asgi_client
from tests.support.credentials import REVOKED_ACCESS_TOKEN, TEST_JELLYFIN_ACCESS_TOKEN
from tests.support.fake_emby import FakeEmbyState, create_fake_emby_app
from tests.support.fake_jellyfin import FakeJellyfinState, create_fake_jellyfin_app


def _config(provider: str, *, require_login: bool = False, dev_host: bool = False) -> Config:
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
        RuntimeConfig(LOG_TO_FILE=False, REQUIRE_LOGIN=require_login),
        private_env=(
            {
                "EMBY_WATCHPARTY_X_DEV_HOST": "Alice:secret",
                "EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK": "true",
            }
            if dev_host
            else None
        ),
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


def test_jellyfin_provider_authenticates_and_verifies_normalized_users() -> None:
    fake_state = FakeJellyfinState()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state))
        ) as client:
            gateway = MediaServerGateway(client, "http://jellyfin.test", logging.getLogger("test"))
            provider = create_provider(_config("jellyfin"), logging.getLogger("test"), gateway)

            user = await provider.authenticate_user("Alice", "secret")

            assert user == AuthenticatedUser(
                credentials=ProviderCredentials(
                    access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                    user_id="jellyfin-user-1",
                ),
                username="Alice",
                is_admin=True,
            )
            assert user is not None
            assert await provider.verify_user(user.credentials) is True

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_type", ["emby", "jellyfin"])
def test_provider_rejects_revoked_user_token(provider_type: str) -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(401))
        ) as client:
            config = _config(provider_type)
            gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))
            provider = create_provider(config, logging.getLogger("test"), gateway)

            verified = await provider.verify_user(
                ProviderCredentials(access_token=REVOKED_ACCESS_TOKEN, user_id="user-1")
            )

            assert verified is False

    asyncio.run(exercise())


def test_jellyfin_v2_login_names_selected_provider_when_unavailable(tmp_path) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.MockTransport(unavailable),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )

            response = await client.post(
                "/api/v2/auth/login",
                json={"username": "Alice", "password": "secret"},
            )

            assert response.status_code == 200
            assert response.json()["message"] == (
                "Jellyfin server unavailable; ask the operator to verify JELLYFIN_SERVER_URL"
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("provider_type", "display_name"),
    [("emby", "Emby"), ("jellyfin", "Jellyfin")],
)
def test_v2_login_names_selected_provider_for_invalid_credentials(
    tmp_path, provider_type: str, display_name: str
) -> None:
    app = create_app(
        config=_config(provider_type),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.MockTransport(lambda _request: httpx.Response(401)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )

            response = await client.post(
                "/api/v2/auth/login",
                json={"username": "Alice", "password": "wrong"},
            )

            assert response.status_code == 200
            assert response.json()["message"] == f"Invalid {display_name} credentials"

    asyncio.run(exercise())


def test_login_required_party_creation_uses_provider_authentication(tmp_path) -> None:
    authenticate_user = AsyncMock(
        return_value=AuthenticatedUser(
            credentials=ProviderCredentials(
                access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                user_id="jellyfin-user-1",
            ),
            username="Alice",
            is_admin=True,
        )
    )

    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

        async def authenticate_user(self, username: str, password: str):
            return await authenticate_user(username, password)

    app = create_app(
        config=_config("jellyfin", require_login=True),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/party/create",
                json={
                    "client_id": "client-1",
                    "display_name": "Alice",
                    "username": "Alice",
                    "password": "secret",
                },
            )

            assert response.status_code == 200
            assert response.json()["is_host"] is True
            authenticate_user.assert_awaited_once_with("Alice", "secret")

    asyncio.run(exercise())


def test_login_required_party_creation_names_selected_provider(tmp_path) -> None:
    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

    app = create_app(
        config=_config("jellyfin", require_login=True),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.post("/api/party/create", json={})

            assert response.status_code == 200
            assert response.json()["message"] == "Jellyfin login is required to create a party"

    asyncio.run(exercise())


def test_standalone_admin_login_uses_provider_authentication(tmp_path) -> None:
    authenticate_user = AsyncMock(
        return_value=AuthenticatedUser(
            credentials=ProviderCredentials(
                access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                user_id="jellyfin-user-1",
            ),
            username="Alice",
            is_admin=True,
        )
    )

    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

        async def authenticate_user(self, username: str, password: str):
            return await authenticate_user(username, password)

    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/admin/login",
                json={"username": "Alice", "password": "secret"},
            )

            assert response.status_code == 200
            assert response.json()["success"] is True
            authenticate_user.assert_awaited_once_with("Alice", "secret")

    asyncio.run(exercise())


def test_stashed_admin_token_is_revalidated_through_provider(tmp_path) -> None:
    authenticated = AuthenticatedUser(
        credentials=ProviderCredentials(
            access_token=TEST_JELLYFIN_ACCESS_TOKEN,
            user_id="jellyfin-user-1",
        ),
        username="Alice",
        is_admin=True,
    )
    verify_user = AsyncMock(return_value=True)

    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

        async def authenticate_user(self, _username: str, _password: str):
            return authenticated

        async def verify_user(self, credentials: ProviderCredentials) -> bool:
            return await verify_user(credentials)

    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            login = await client.post(
                "/api/admin/login",
                json={"username": "Alice", "password": "secret"},
            )
            assert login.json()["success"] is True

            created = await client.post(
                "/api/party/create",
                json={"client_id": "client-1", "display_name": "Alice"},
            )

            assert created.json()["is_host"] is True
            verify_user.assert_awaited_once_with(authenticated.credentials)

    asyncio.run(exercise())


def test_dev_auto_host_join_uses_provider_authentication(tmp_path) -> None:
    authenticate_user = AsyncMock(
        return_value=AuthenticatedUser(
            credentials=ProviderCredentials(
                access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                user_id="jellyfin-user-1",
            ),
            username="Alice",
            is_admin=True,
        )
    )

    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

        async def authenticate_user(self, username: str, password: str):
            return await authenticate_user(username, password)

    app = create_app(
        config=_config("jellyfin", dev_host=True),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]

            joined = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )

            assert joined.json()["is_host"] is True
            authenticate_user.assert_awaited_once_with("Alice", "secret")

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("provider_type", "filter_controls"),
    [("emby", True), ("jellyfin", True)],
)
def test_media_server_info_declares_filter_capability(
    tmp_path, provider_type: str, filter_controls: bool
) -> None:
    app = create_app(
        config=_config(provider_type),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            response = await client.get("/api/v2/media-server")

            assert response.status_code == 200
            assert response.json()["capabilities"] == {"filter_controls": filter_controls}

    asyncio.run(exercise())


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


@pytest.mark.parametrize("version", ["10.10.7", "10.11.11"])
def test_jellyfin_v2_supported_filters_use_root_items_and_server_side_scope(
    tmp_path, version: str
) -> None:
    fake_state = FakeJellyfinState(version=version)
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
                    "filters": {
                        "playstate": "resumable",
                        "favorite": True,
                        "genres": ["Drama", "Science Fiction"],
                        "studios": ["Paramount", "Warner Bros."],
                        "person_ids": ["person-1", "person-2"],
                        "years": [2020, 2024],
                        "official_ratings": ["PG", "PG-13"],
                        "community_rating_min": 7.5,
                        "critic_rating_min": 80,
                        "tags": ["must-not-reach-jellyfin"],
                    },
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
    item_request = next(row for row in fake_state.requests if row["path"] == "/Items")
    assert item_request == {
        "method": "GET",
        "path": "/Items",
        "query": {
            "UserId": "jellyfin-user-1",
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
            "Filters": "IsResumable",
            "IsFavorite": "true",
            "Genres": "Drama|Science Fiction",
            "Studios": "Paramount|Warner Bros.",
            "PersonIds": "person-1,person-2",
            "Years": "2020,2024",
            "OfficialRatings": "PG|PG-13",
            "MinCommunityRating": "7.5",
            "MinCriticRating": "80.0",
        },
    }


def test_emby_v2_rating_filters_use_separate_server_side_minimums(tmp_path) -> None:
    fake_state = FakeEmbyState()
    app = create_app(
        config=_config("emby"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_emby_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )

            options = await client.get("/api/v2/items/filter-options")
            response = await client.post(
                "/api/v2/items/query",
                json={
                    "scope": {"include_kinds": ["movie"], "recursive": True},
                    "filters": {"community_rating_min": 7.5, "critic_rating_min": 80},
                },
            )

            assert options.status_code == 200
            community = next(
                control
                for control in options.json()["controls"]
                if control["id"] == "community_rating"
            )
            assert community["label"] == "Community rating"
            critic = next(
                control
                for control in options.json()["controls"]
                if control["id"] == "critic_rating"
            )
            assert critic["label"] == "Critic rating"
            assert response.status_code == 200

    asyncio.run(exercise())
    item_request = next(
        row for row in reversed(fake_state.requests) if row["path"] == "/emby/Users/user-1/Items"
    )
    assert dict(item_request["query"])["MinCommunityRating"] == "7.5"
    assert dict(item_request["query"])["MinCriticRating"] == "80.0"


def test_jellyfin_v2_prefixes_probe_supported_item_queries(tmp_path) -> None:
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
                "/api/v2/items/prefixes",
                json={"scope": {"parent_id": "jellyfin-library-1"}},
            )

            assert response.status_code == 200
            assert response.json() == {"prefixes": ["A", "#"]}

    asyncio.run(exercise())
    assert not any(request["path"] == "/Items/Prefixes" for request in fake_state.requests)
    prefix_requests = [
        request
        for request in fake_state.requests
        if request["path"] == "/Users/jellyfin-user-1/Items"
        and request["query"].get("EnableTotalRecordCount") == "true"
    ]
    assert len(prefix_requests) == 27
    assert {request["query"].get("NameStartsWith") for request in prefix_requests} == {
        None,
        *"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    }


def test_jellyfin_v2_upstream_error_names_selected_provider(tmp_path) -> None:
    authenticated = AuthenticatedUser(
        credentials=ProviderCredentials(
            access_token=TEST_JELLYFIN_ACCESS_TOKEN,
            user_id="jellyfin-user-1",
        ),
        username="Alice",
        is_admin=True,
    )

    class ProviderDouble:
        identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

        async def authenticate_user(self, _username: str, _password: str):
            return authenticated

        async def query_prefixes(self, _query, _credentials):
            raise httpx.ConnectError("server unavailable")

    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )
    app.dependency_overrides[get_media_server] = ProviderDouble

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )

            response = await client.post("/api/v2/items/prefixes", json={"scope": {}})

            assert response.status_code == 502
            assert response.json() == {"detail": "Jellyfin upstream unavailable"}

    asyncio.run(exercise())


def test_jellyfin_v2_filter_options_use_scoped_catalogs_without_item_scan(tmp_path) -> None:
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
            before = len(fake_state.requests)
            response = await client.get(
                "/api/v2/items/filter-options",
                params={
                    "parent_id": "jellyfin-library-1",
                    "include_kinds": "movie,series",
                    "media_kinds": "video",
                },
            )

            assert response.status_code == 200
            controls = response.json()["controls"]
            assert [control["id"] for control in controls] == [
                "playstate",
                "favorite",
                "year",
                "official_rating",
                "community_rating",
                "critic_rating",
                "genre",
                "studio",
            ]
            by_id = {control["id"]: control for control in controls}
            current_year = str(datetime.now(UTC).year)
            assert by_id["year"]["values"][0] == {
                "value": current_year,
                "label": current_year,
            }
            assert by_id["year"]["values"][-1] == {"value": "1888", "label": "1888"}
            assert [value["value"] for value in by_id["official_rating"]["values"]] == [
                "G",
                "PG",
                "PG-13",
                "R",
                "NC-17",
                "TV-Y",
                "TV-Y7",
                "TV-G",
                "TV-PG",
                "TV-14",
                "TV-MA",
                "NR",
                "Unrated",
            ]
            assert by_id["community_rating"] == {
                "id": "community_rating",
                "label": "Community rating",
                "kind": "select",
                "values": [
                    {"value": "5", "label": "5+"},
                    {"value": "6", "label": "6+"},
                    {"value": "7", "label": "7+"},
                    {"value": "8", "label": "8+"},
                    {"value": "9", "label": "9+"},
                ],
            }
            assert by_id["critic_rating"] == {
                "id": "critic_rating",
                "label": "Critic rating",
                "kind": "select",
                "values": [
                    {"value": "50", "label": "50%+"},
                    {"value": "60", "label": "60%+"},
                    {"value": "70", "label": "70%+"},
                    {"value": "80", "label": "80%+"},
                    {"value": "90", "label": "90%+"},
                ],
            }
            assert [value["value"] for value in by_id["genre"]["values"]] == [
                "Drama",
                "Science Fiction",
            ]
            assert [value["value"] for value in by_id["studio"]["values"]] == ["Paramount"]
            catalog_requests = fake_state.requests[before:]
            assert catalog_requests == [
                {
                    "method": "GET",
                    "path": "/Genres",
                    "query": {
                        "userId": "jellyfin-user-1",
                        "parentId": "jellyfin-library-1",
                        "includeItemTypes": "Movie,Series",
                        "enableImages": "false",
                    },
                },
                {
                    "method": "GET",
                    "path": "/Studios",
                    "query": {
                        "userId": "jellyfin-user-1",
                        "parentId": "jellyfin-library-1",
                        "includeItemTypes": "Movie,Series",
                        "enableImages": "false",
                    },
                },
            ]
            assert all(request["path"] != "/Items" for request in catalog_requests)

    asyncio.run(exercise())


def test_jellyfin_v2_filter_options_omit_only_failed_dynamic_catalog(tmp_path) -> None:
    fake_state = FakeJellyfinState(failing_catalogs={"genres"})
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (
                await client.post(
                    "/api/party/create",
                    json={"client_id": "client-1", "display_name": "Alice"},
                )
            ).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            await client.post(
                "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
            )

            response = await client.get(
                "/api/v2/items/filter-options",
                params={"parent_id": "jellyfin-library-1"},
            )

            assert response.status_code == 200
            controls = response.json()["controls"]
            assert [control["id"] for control in controls] == [
                "playstate",
                "favorite",
                "year",
                "official_rating",
                "community_rating",
                "critic_rating",
                "studio",
            ]
            serialized = response.text
            assert "secret-token" not in serialized
            assert "jellyfin.internal" not in serialized

    asyncio.run(exercise())


def test_jellyfin_v2_grouped_search_groups_normalized_items(tmp_path) -> None:
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
            response = await client.get("/api/v2/items/search/groups", params={"q": "Arrival"})

            assert response.status_code == 200
            payload = response.json()
            assert payload["query"] == "Arrival"
            assert payload["groups"][0]["id"] == "movies"
            assert payload["groups"][0]["items"][0]["id"] == "movie-1"

    asyncio.run(exercise())


def test_jellyfin_v2_item_sections_are_normalized(tmp_path) -> None:
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
            response = await client.get("/api/v2/items/movie-1/sections/related")

            assert response.status_code == 200
            assert response.json()["section"] == "related"
            assert response.json()["items"][0]["id"] == "movie-related"

    asyncio.run(exercise())


def test_jellyfin_catalog_projects_through_legacy_v1_contracts(tmp_path) -> None:
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

            libraries = await client.get("/api/libraries")
            items = await client.get("/api/items", params={"parentId": "jellyfin-library-1"})
            details = await client.get("/api/item/movie-1")

            assert libraries.json()["Items"][0]["Id"] == "jellyfin-library-1"
            assert items.json()["Items"][0]["Id"] == "movie-1"
            assert details.json()["Id"] == "movie-1"
            assert details.json()["Genres"] == ["Drama", "Science Fiction"]

    asyncio.run(exercise())


def test_jellyfin_host_avatar_uses_provider_root_route(tmp_path) -> None:
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
            response = await client.get(f"/api/avatar/host/{party_id}")

            assert response.status_code == 200
            assert response.content == b"jellyfin-avatar"
            assert response.headers["x-content-type-options"] == "nosniff"

    asyncio.run(exercise())
    assert any(
        request["path"] == "/Users/jellyfin-user-1/Images/Primary"
        for request in fake_state.requests
    )


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
            assert payload["tagline"] == "Why are they here?"
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
    # Index 4 is a text track, so it is NOT named here. Naming it asks Jellyfin
    # to deliver it, and with no matching SubtitleProfile that means burning it
    # into the video, on top of the <track> the frontend already loaded.
    # -1 rather than null: null means "no preference" and lets the account's
    # SubtitlePlaybackMode pick a track for us.
    assert request["SubtitleStreamIndex"] == -1
    assert request["AlwaysBurnInSubtitleWhenTranscoding"] is False
    assert request["MaxStreamingBitrate"] == 4_000_000
    assert request["EnableDirectPlay"] is False
    assert request["EnableDirectStream"] is True
    assert request["EnableTranscoding"] is True
    assert request["AllowVideoStreamCopy"] is True
    profile = request["DeviceProfile"]
    assert profile["Name"] == "Emby Watch Party HLS"
    assert profile["TranscodingProfiles"][0]["Protocol"] == "hls"
    assert profile["TranscodingProfiles"][0]["Container"] == "ts"
    # Subtitles must not ride in the manifest. hls.js would build a text track
    # from an #EXT-X-MEDIA rendition while the frontend is already showing the
    # same lines from its own <track>, which is the second route to doubled
    # subtitles and survives the burn-in fix. Jellyfin defaults this to false;
    # asking for true was the bug.
    assert profile["TranscodingProfiles"][0]["EnableSubtitlesInManifest"] is False


def test_jellyfin_text_subtitle_negotiates_once_and_is_never_burned_in(tmp_path) -> None:
    """A text track must not reach Jellyfin's subtitle pipeline at all.

    The DeviceProfile advertises only vtt and srt as External, so an ass/ssa
    track matches no profile and Jellyfin falls back to Encode, burning it into
    the video while the frontend is already rendering the same lines from the
    subtitle asset route. The viewer sees every line twice, slightly offset.
    """
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app):
            await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                    media_source_id="source-1",
                    subtitle_index=4,
                    quality="720p-4000",
                )
            )

    asyncio.run(exercise())
    # One round trip: the text case never needs to re-negotiate.
    assert len(fake_state.playback_requests) == 1
    # Explicitly -1. A null here is "no preference", which hands the choice to
    # the account's SubtitlePlaybackMode and can auto-select a track we then
    # burn in, which is the bug this test is named after.
    assert fake_state.playback_requests[0]["SubtitleStreamIndex"] == -1
    assert fake_state.playback_requests[0]["AlwaysBurnInSubtitleWhenTranscoding"] is False


def test_jellyfin_image_subtitle_is_burned_in_on_a_second_negotiation(tmp_path) -> None:
    """Bitmap tracks are the one case that genuinely must be burned in.

    hls.js cannot draw PGS or VobSub, so there is no side-channel path and the
    server has to composite it. Index 5 in the fake is a PGS track.
    """
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app):
            await app.state.media_server.prepare_playback(
                PlaybackRequest(
                    item_id="movie-1",
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                    media_source_id="source-1",
                    subtitle_index=5,
                    quality="720p-4000",
                )
            )

    asyncio.run(exercise())
    # The stream catalog only arrives in the response, so classifying the track
    # costs a second call. The first must still not name the subtitle, or a
    # server that honours it would burn the track in during the throwaway pass.
    assert len(fake_state.playback_requests) == 2
    assert fake_state.playback_requests[0]["SubtitleStreamIndex"] == -1
    assert fake_state.playback_requests[1]["SubtitleStreamIndex"] == 5
    assert fake_state.playback_requests[1]["AlwaysBurnInSubtitleWhenTranscoding"] is True


def test_no_playback_info_request_ever_leaves_the_subtitle_unspecified() -> None:
    """A null SubtitleStreamIndex is the bug, not a neutral value.

    Jellyfin reads null as "no preference" and falls back to the media source's
    DefaultSubtitleStreamIndex, which follows the account's SubtitlePlaybackMode.
    An account set to always show subtitles then gets a track auto-selected and,
    with only vtt/srt advertised as External, burned into the video.

    httpx serialises None as JSON null rather than dropping the key, so this is
    reachable purely by passing None where -1 was meant.
    """
    adapter = Path(__file__).resolve().parents[1] / "backend" / "src" / "providers" / "jellyfin.py"
    source = adapter.read_text(encoding="utf-8")

    assert "NO_SUBTITLE = -1" in source
    assert "negotiate(NO_SUBTITLE)" in source
    assert "negotiate(None)" not in source


def test_stop_playback_reports_failure_instead_of_raising(tmp_path) -> None:
    """The Protocol says `-> bool`, and _stop_user_stream has no try/except.

    EmbyProvider cannot raise here: EmbyClient._report and stop_active_encodings
    both swallow httpx.HTTPError and return False. Jellyfin must match. If it
    raises, an expired host token on stop skips hls_registry.revoke, aborts
    _stop_all_user_streams part-way so every remaining viewer keeps a live plan
    and a running transcode, and wedges the party with a video that will not
    stop.
    """
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    event = PlaybackEvent(
        type=PlaybackEventType.STOP,
        item_id="movie-1",
        media_source_id="source-1",
        play_session_id="jellyfin-play-session-1",
        position_seconds=1.0,
        run_time_seconds=100.0,
        credentials=ProviderCredentials(
            access_token=TEST_JELLYFIN_ACCESS_TOKEN,
            user_id="jellyfin-user-1",
        ),
        is_paused=False,
    )

    # Both shapes the gateway can produce: a transport failure, and a non-2xx
    # turned into an exception by raise_for_status. The gateway retries only
    # GET/HEAD, so a POST gets neither a retry nor a swallow underneath us.
    failures = [
        httpx.ConnectError("jellyfin went away"),
        httpx.HTTPStatusError(
            "401 Unauthorized",
            request=httpx.Request("POST", "http://jellyfin.test/Sessions/Playing/Stopped"),
            response=httpx.Response(401),
        ),
    ]

    async def exercise() -> None:
        async with asgi_client(app):
            provider = app.state.media_server
            for failure in failures:
                provider._client.gateway.post = AsyncMock(side_effect=failure)
                assert await provider.stop_playback(event) is False, (
                    f"stop_playback raised or reported success on {type(failure).__name__}; "
                    "_stop_user_stream has no try/except and will skip hls_registry.revoke"
                )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        ({"Type": "Subtitle", "Index": 3, "IsTextSubtitleStream": True}, False),
        ({"Type": "Subtitle", "Index": 3, "IsTextSubtitleStream": False}, True),
        # A server that omits the flag falls back to the codec list.
        ({"Type": "Subtitle", "Index": 3, "Codec": "pgssub"}, True),
        ({"Type": "Subtitle", "Index": 3, "Codec": "vobsub"}, True),
        ({"Type": "Subtitle", "Index": 3, "Codec": "ass"}, False),
        ({"Type": "Subtitle", "Index": 3, "Codec": "subrip"}, False),
        # The flag wins over the codec when both are present.
        ({"Type": "Subtitle", "Index": 3, "Codec": "pgssub", "IsTextSubtitleStream": True}, False),
        # Wrong index, and an audio stream that happens to share the index.
        ({"Type": "Subtitle", "Index": 9, "IsTextSubtitleStream": False}, False),
        ({"Type": "Audio", "Index": 3, "IsTextSubtitleStream": False}, False),
    ],
)
def test_subtitle_burn_in_classification(stream, expected) -> None:
    assert _subtitle_must_be_burned_in({"MediaStreams": [stream]}, 3) is expected


def test_subtitle_burn_in_defaults_to_not_burning_when_the_track_is_absent() -> None:
    """Not burning in is the recoverable failure; a burned-in track is permanent."""
    assert _subtitle_must_be_burned_in({}, 3) is False
    assert _subtitle_must_be_burned_in({"MediaStreams": []}, 3) is False


def test_jellyfin_accepts_hyphenated_guid_in_server_hls_path(tmp_path) -> None:
    compact_id = "cc196d0f967bf87cd071dd7092c4134a"
    hyphenated_id = "cc196d0f-967b-f87c-d071-dd7092c4134a"
    fake_state = FakeJellyfinState(playback_path_item_id=hyphenated_id)
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
                    item_id=compact_id,
                    credentials=ProviderCredentials(
                        access_token=TEST_JELLYFIN_ACCESS_TOKEN,
                        user_id="jellyfin-user-1",
                    ),
                    media_source_id="source-1",
                )
            )

            assert plan.master.url.startswith(
                f"http://jellyfin.test/Videos/{hyphenated_id}/master.m3u8?"
            )

    asyncio.run(exercise())


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


def test_socket_disconnect_revokes_the_viewers_jellyfin_plan(tmp_path) -> None:
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
            assert app.state.hls_registry.get_plan(stream.stream_id) is not None

            await app.state.sio.handlers["/"]["disconnect"](sid)

            assert app.state.hls_registry.get_plan(stream.stream_id) is None

    asyncio.run(exercise())


def test_socket_rejoin_revokes_the_replaced_jellyfin_plan(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app(fake_state)),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id = (await client.post("/api/party/create", json={})).json()["party_id"]
            party = app.state.party_manager.get(party_id)
            assert party is not None
            old_sid = "old-socket"
            party.current_video = SelectedMedia(item_id="movie-1", title="Arrival")
            party.sid_client_ids[old_sid] = "client-1"
            party.participants["client-1"] = Participant(
                client_id="client-1", username="Alice", sid=old_sid
            )

            old_stream = await app.state.socket_context["create_user_stream"](
                party,
                party_id,
                old_sid,
                "movie-1",
                None,
                2,
                4,
                "720p-4000",
                start_seconds=12.5,
                media_source_id="source-1",
            )
            assert old_stream is not None
            assert old_stream.stream_id
            assert app.state.hls_registry.get_plan(old_stream.stream_id) is not None
            # Model a dropped transport whose disconnect callback has not run
            # before the browser's replacement socket rejoins.
            party.sid_client_ids.pop(old_sid)

            new_sid = await app.state.sio.manager.connect("new-engine-socket", "/")
            await app.state.sio.handlers["/"]["join_party"](
                new_sid,
                {"party_id": party_id, "username": "Alice", "client_id": "client-1"},
            )

            assert app.state.hls_registry.get_plan(old_stream.stream_id) is None

    asyncio.run(exercise())


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
        if row["path"] == "/Items" and row["query"].get("SearchTerm") == "Arrival"
    )
    assert request["query"]["UserId"] == "jellyfin-user-1"
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
                    },
                    {
                        "index": 5,
                        "language": "jpn",
                        "display_language": "Japanese (PGS)",
                        "codec": "pgssub",
                        "is_default": False,
                        "is_forced": False,
                        "is_external": False,
                        "is_text": False,
                        "is_image": True,
                        "title": "",
                    },
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
