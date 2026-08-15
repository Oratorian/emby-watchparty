from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, Request

from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN


@dataclass
class FakeJellyfinState:
    requests: list[dict] = field(default_factory=list)
    playback_requests: list[dict] = field(default_factory=list)

    def record(self, request: Request) -> None:
        query = {
            key: "<redacted>" if key.lower() in {"api_key", "access_token"} else value
            for key, value in request.query_params.items()
        }
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": query,
            }
        )


def create_fake_jellyfin_app(state: FakeJellyfinState | None = None) -> FastAPI:
    state = state or FakeJellyfinState()
    app = FastAPI(title="Fake Jellyfin", docs_url=None, redoc_url=None)

    @app.get("/System/Info/Public")
    async def public_info(request: Request):
        state.record(request)
        return {"ServerName": "Fake Jellyfin", "Version": "10.11.11"}

    @app.get("/System/Info")
    async def system_info(request: Request):
        state.record(request)
        return {"ServerName": "Fake Jellyfin", "Version": "10.11.11"}

    @app.post("/Users/AuthenticateByName")
    async def authenticate(request: Request):
        body = await request.json()
        state.record(request)
        return {
            "AccessToken": TEST_JELLYFIN_ACCESS_TOKEN,
            "User": {
                "Id": "jellyfin-user-1",
                "Name": body.get("Username", "Alice"),
                "Policy": {"IsAdministrator": True},
            },
        }

    @app.post("/Sessions/Capabilities/Full")
    async def capabilities(request: Request):
        state.record(request)
        return {}

    @app.get("/Users/{user_id}")
    async def user(user_id: str, request: Request):
        state.record(request)
        return {"Id": user_id, "Name": "Alice"}

    @app.get("/UserViews")
    async def user_views(request: Request):
        state.record(request)
        return {
            "Items": [
                {
                    "Id": "jellyfin-library-1",
                    "Name": "Movies",
                    "Type": "CollectionFolder",
                    "CollectionType": "movies",
                    "IsFolder": True,
                    "ImageTags": {"Primary": "image-tag"},
                }
            ],
            "TotalRecordCount": 1,
            "StartIndex": 0,
        }

    @app.get("/Users/{user_id}/Items")
    async def user_items(user_id: str, request: Request):
        assert user_id
        state.record(request)
        return {
            "Items": [
                {
                    "Id": "movie-1",
                    "Name": "Arrival",
                    "Type": "Movie",
                    "RunTimeTicks": 6_960_000_000,
                    "ProductionYear": 2016,
                    "ImageTags": {"Primary": "movie-image"},
                    "UserData": {"IsFavorite": True, "Played": False},
                    "MediaSourceCount": 1,
                }
            ],
            "TotalRecordCount": 1,
            "StartIndex": int(request.query_params.get("StartIndex", "0")),
        }

    @app.get("/Users/{user_id}/Items/{item_id}")
    async def item_details(user_id: str, item_id: str, request: Request):
        assert user_id
        state.record(request)
        return {
            "Id": item_id,
            "Name": "Arrival",
            "Type": "Movie",
            "Overview": "A linguist meets visitors.",
            "RunTimeTicks": 6_960_000_000,
            "ProductionYear": 2016,
            "OfficialRating": "PG-13",
            "CommunityRating": 7.9,
            "CriticRating": 94,
            "Genres": ["Drama", "Science Fiction"],
            "Tags": ["First contact"],
            "People": [{"Id": "person-1", "Name": "Amy Adams", "Type": "Actor"}],
            "Studios": [{"Name": "Paramount"}],
            "ImageTags": {"Primary": "movie-image"},
            "BackdropImageTags": ["backdrop-image"],
            "UserData": {"IsFavorite": True, "Played": False},
            "MediaSourceCount": 1,
        }

    @app.post("/Items/{item_id}/PlaybackInfo")
    async def playback_info(item_id: str, request: Request):
        body = await request.json()
        state.record(request)
        state.playback_requests.append(body)
        return {
            "PlaySessionId": "jellyfin-play-session-1",
            "MediaSources": [
                {
                    "Id": body.get("MediaSourceId") or "source-1",
                    "TranscodingUrl": (
                        f"/Videos/{item_id}/master.m3u8?MediaSourceId=source-1&"
                        "PlaySessionId=jellyfin-play-session-1&"
                        f"api_key={TEST_JELLYFIN_ACCESS_TOKEN}"
                    ),
                    "TranscodingSubProtocol": "hls",
                    "TranscodingContainer": "ts",
                    "TranscodingReasons": ["VideoCodecNotSupported"],
                }
            ],
        }

    return app
