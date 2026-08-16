from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import Response

from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN


@dataclass
class FakeJellyfinState:
    requests: list[dict] = field(default_factory=list)
    request_hosts: list[str] = field(default_factory=list)
    playback_requests: list[dict] = field(default_factory=list)
    playback_reports: list[dict] = field(default_factory=list)
    playback_path_item_id: str | None = None

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
        self.request_hosts.append(request.url.netloc)


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

    @app.get("/Users/{user_id}/Images/Primary")
    async def user_avatar(user_id: str, request: Request):
        assert user_id
        state.record(request)
        return Response(b"jellyfin-avatar", media_type="image/png")

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
        if request.query_params.get("EnableTotalRecordCount") == "true":
            prefix = request.query_params.get("NameStartsWith")
            if prefix == "A":
                return {"Items": [{"Id": "movie-1", "Name": "Arrival"}], "TotalRecordCount": 1}
            if prefix:
                return {"Items": [], "TotalRecordCount": 0}
            return {
                "Items": [{"Id": "symbol-movie", "Name": "'71"}],
                "TotalRecordCount": 2,
            }
        if request.query_params.get("IncludeItemTypes") == "Playlist":
            return {
                "Items": [
                    {
                        "Id": "playlist-1",
                        "Name": "Movie Night",
                        "Type": "Playlist",
                        "IsFolder": True,
                        "UserData": {"IsFavorite": False, "Played": False},
                    }
                ],
                "TotalRecordCount": 1,
                "StartIndex": 0,
            }
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

    @app.get("/Items/Prefixes")
    async def item_prefixes(request: Request):
        state.record(request)
        return [{"Name": "A"}, {"Name": "#"}]

    @app.get("/Users/{user_id}/Items/{item_id}")
    async def item_details(user_id: str, item_id: str, request: Request):
        assert user_id
        state.record(request)
        return {
            "Id": item_id,
            "Name": "Arrival",
            "Type": "Movie",
            "Overview": "A linguist meets visitors.",
            "Tagline": "Why are they here?",
            "Taglines": ["Fallback tagline"],
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

    @app.get("/Items/{item_id}/Similar")
    async def similar_items(item_id: str, request: Request):
        assert item_id
        state.record(request)
        return {
            "Items": [{"Id": "movie-related", "Name": "Contact", "Type": "Movie"}],
            "TotalRecordCount": 1,
        }

    @app.get("/Items/{item_id}/Images/{image_type}")
    @app.get("/Items/{item_id}/Images/{image_type}/{image_index}")
    async def item_image(
        item_id: str,
        image_type: str,
        request: Request,
        image_index: int | None = None,
    ):
        del image_index
        assert item_id
        assert image_type
        state.record(request)
        return Response(b"jellyfin-image", media_type="image/png")

    @app.get("/Videos/{item_id}/{media_source_id}/Subtitles/{subtitle_index}/Stream.vtt")
    async def subtitle(
        item_id: str,
        media_source_id: str,
        subtitle_index: int,
        request: Request,
    ):
        assert item_id
        assert media_source_id
        assert subtitle_index >= 0
        state.record(request)
        return Response("WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n", media_type="text/vtt")

    @app.get("/MediaSegments/{item_id}")
    async def media_segments(item_id: str, request: Request):
        assert item_id
        state.record(request)
        return {
            "Items": [
                {
                    "Type": "Intro",
                    "StartTicks": 25_000_000,
                    "EndTicks": 925_000_000,
                }
            ]
        }

    @app.get("/Shows/{series_id}/Seasons")
    async def seasons(series_id: str, request: Request):
        state.record(request)
        return {
            "Items": [
                {
                    "Id": "season-1",
                    "Name": "Season 1",
                    "Type": "Season",
                    "SeriesId": series_id,
                    "IndexNumber": 1,
                    "IsFolder": True,
                }
            ],
            "TotalRecordCount": 1,
        }

    @app.get("/Shows/{series_id}/Episodes")
    async def episodes(series_id: str, request: Request):
        state.record(request)
        season_id = request.query_params.get("SeasonId")
        return {
            "Items": [
                {
                    "Id": "episode-1",
                    "Name": "Pilot",
                    "Type": "Episode",
                    "SeriesId": series_id,
                    "SeriesName": "Example Series",
                    "SeasonId": season_id,
                    "SeasonName": "Season 1",
                    "IndexNumber": 1,
                    "ParentIndexNumber": 1,
                    "RunTimeTicks": 2_400_000_000,
                }
            ],
            "TotalRecordCount": 1,
        }

    @app.api_route("/Users/{user_id}/FavoriteItems/{item_id}", methods=["POST", "DELETE"])
    async def favorite(user_id: str, item_id: str, request: Request):
        assert user_id
        assert item_id
        state.record(request)
        return {}

    @app.api_route("/Users/{user_id}/PlayedItems/{item_id}", methods=["POST", "DELETE"])
    async def played(user_id: str, item_id: str, request: Request):
        assert user_id
        assert item_id
        state.record(request)
        return {}

    @app.post("/Playlists")
    async def create_playlist(request: Request):
        state.record(request)
        return {"Id": "playlist-created"}

    @app.post("/Playlists/{playlist_id}/Items")
    async def add_playlist_item(playlist_id: str, request: Request):
        assert playlist_id
        state.record(request)
        return {}

    @app.post("/Items/{item_id}/PlaybackInfo")
    async def playback_info(item_id: str, request: Request):
        body = await request.json()
        state.record(request)
        state.playback_requests.append(body)
        streams = [
            {
                "Type": "Audio",
                "Index": 1,
                "Language": "eng",
                "DisplayTitle": "English Stereo",
                "Codec": "aac",
                "Channels": 2,
                "IsDefault": True,
                "Title": "Main",
            },
            {
                "Type": "Subtitle",
                "Index": 4,
                "Language": "spa",
                "DisplayTitle": "Spanish",
                "Codec": "srt",
                "IsExternal": True,
                "IsTextSubtitleStream": True,
            },
        ]
        sources = [
            {
                "Id": "source-1",
                "Name": "1080p",
                "Container": "mkv",
                "RunTimeTicks": 6_960_000_000,
                "MediaStreams": streams,
            },
            {
                "Id": "source-2",
                "Name": "4K",
                "Container": "mkv",
                "RunTimeTicks": 6_960_000_000,
                "MediaStreams": streams,
            },
        ]
        selected_id = body.get("MediaSourceId")
        if selected_id:
            sources = [source for source in sources if source["Id"] == selected_id]
        for source in sources:
            path_item_id = state.playback_path_item_id or item_id
            source.update(
                {
                    "TranscodingUrl": (
                        f"/Videos/{path_item_id}/master.m3u8?MediaSourceId={source['Id']}&"
                        "PlaySessionId=jellyfin-play-session-1&"
                        f"api_key={TEST_JELLYFIN_ACCESS_TOKEN}"
                    ),
                    "TranscodingSubProtocol": "hls",
                    "TranscodingContainer": "ts",
                    "TranscodingReasons": ["VideoCodecNotSupported"],
                }
            )
        return {
            "PlaySessionId": "jellyfin-play-session-1",
            "MediaSources": sources,
        }

    @app.api_route("/emby/Videos/{item_id}/master.m3u8", methods=["GET", "HEAD"])
    @app.api_route("/Videos/{item_id}/master.m3u8", methods=["GET", "HEAD"])
    async def master_playlist(item_id: str, request: Request):
        assert item_id
        state.record(request)
        return Response(
            '#EXTM3U\r\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="subs/en.M3U8?lang=en"\r\n'
            "main.M3U8?quality=high\r\n",
            media_type="application/vnd.apple.mpegurl",
        )

    @app.get("/Videos/{item_id}/main.M3U8")
    async def media_playlist(item_id: str, request: Request):
        assert item_id
        state.record(request)
        return Response(
            "#EXTM3U\n#EXTINF:6.0,\nsegments/segment0001.ts?part=1\n",
            media_type="application/vnd.apple.mpegurl",
        )

    @app.api_route("/Videos/{item_id}/segments/segment0001.ts", methods=["GET", "HEAD"])
    async def segment(item_id: str, request: Request):
        assert item_id
        state.record(request)
        content = b"0123456789"
        if request.headers.get("range") == "bytes=2-5":
            return Response(
                content[2:6],
                status_code=206,
                media_type="video/MP2T",
                headers={
                    "Content-Range": "bytes 2-5/10",
                    "Accept-Ranges": "bytes",
                    "Content-Length": "4",
                },
            )
        return Response(
            content,
            media_type="video/MP2T",
            headers={"Accept-Ranges": "bytes", "Content-Length": "10"},
        )

    async def record_playback_report(request: Request):
        body = await request.json()
        state.record(request)
        state.playback_reports.append({"path": request.url.path, "body": body})
        return {}

    app.post("/Sessions/Playing")(record_playback_report)
    app.post("/Sessions/Playing/Progress")(record_playback_report)
    app.post("/Sessions/Playing/Stopped")(record_playback_report)

    return app
