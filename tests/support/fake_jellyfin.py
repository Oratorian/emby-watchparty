from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, Request


@dataclass
class FakeJellyfinState:
    requests: list[dict] = field(default_factory=list)

    def record(self, request: Request) -> None:
        self.requests.append({"method": request.method, "path": request.url.path})


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
            "AccessToken": "jellyfin-user-token",
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

    return app
