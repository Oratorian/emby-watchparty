"""Protocol-faithful, loopback-only Emby test server."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SEGMENT_BYTES = (Path(__file__).parent / "assets" / "fake_segment.ts").read_bytes()
_ARTIFACT_ROOT = Path(__file__).parents[1] / "artifacts" / "emby" / "4.9.5.0"
_FILTER_ARTIFACT_NAMES = {
    "Genres": ("filter-options", "Drama"),
    "Studios": ("studios", "Studio A"),
    "Tags": ("tags", "Featured"),
    "Years": ("years", "2024"),
    "OfficialRatings": ("official-ratings", "PG-13"),
    "Containers": ("containers", "mkv"),
    "VideoCodecs": ("video-codecs", "h264"),
    "AudioCodecs": ("audio-codecs", "aac"),
    "AudioLayouts": ("audio-layouts", "stereo"),
    "SubtitleCodecs": ("subtitle-codecs", "subrip"),
}
_SEGMENT_CHUNKS = [
    _SEGMENT_BYTES[: len(_SEGMENT_BYTES) // 2],
    _SEGMENT_BYTES[len(_SEGMENT_BYTES) // 2 :],
]
# 1x1 transparent PNG, served by the artwork endpoint.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


MOVIE: dict[str, Any] = {
    "Id": "movie-1",
    "Name": "Fake Movie",
    "Type": "Movie",
    "Overview": "A deterministic movie served by fake Emby.",
    "RunTimeTicks": 6_000_000_000,
    "MediaSourceCount": 1,
    "UserData": {"PlaybackPositionTicks": 0, "Played": False},
    "MediaSources": [
        {
            "Id": "source-1",
            "Name": "Fake Source",
            "Container": "mkv",
            "RunTimeTicks": 6_000_000_000,
            "MediaStreams": [
                {
                    "Index": 0,
                    "Type": "Video",
                    "Codec": "h264",
                    "Width": 1920,
                    "Height": 1080,
                    "BitRate": 4_000_000,
                },
                {
                    "Index": 1,
                    "Type": "Audio",
                    "Codec": "aac",
                    "Language": "eng",
                    "DisplayTitle": "English AAC",
                    "Channels": 2,
                    "IsDefault": True,
                },
                {
                    "Index": 2,
                    "Type": "Audio",
                    "Codec": "aac",
                    "Language": "spa",
                    "DisplayTitle": "Spanish AAC",
                    "Channels": 2,
                    "IsDefault": False,
                },
                {
                    "Index": 3,
                    "Type": "Subtitle",
                    "Codec": "subrip",
                    "Language": "eng",
                    "DisplayTitle": "English SRT",
                    "IsDefault": False,
                    "IsExternal": True,
                    "IsTextSubtitleStream": True,
                },
            ],
        }
    ],
}


@dataclass
class FakeEmbyBehavior:
    delays_ms: dict[str, int] = field(default_factory=dict)
    transient_failures: dict[str, int] = field(default_factory=dict)
    transient_status: int = 503
    segment_chunks: list[bytes] = field(default_factory=lambda: list(_SEGMENT_CHUNKS))
    segment_delay_ms: int = 0
    # Emby sits behind its own routing and can answer a segment with a
    # redirect. The shared httpx client runs with follow_redirects=False,
    # so the proxy has to decide what to do with one.
    redirect_segments: bool = False
    master_playlist: str = (
        "#EXTM3U\r\n#EXT-X-VERSION:3\r\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc1.42c00d,mp4a.40.2"\r\n'
        "main.m3u8\r\n"
    )
    variant_playlist: str = (
        "#EXTM3U\r\n#EXT-X-VERSION:3\r\n#EXT-X-TARGETDURATION:10\r\n"
        "#EXT-X-MEDIA-SEQUENCE:0\r\n#EXTINF:10.0,\r\nsegment0.ts\r\n"
        "#EXT-X-ENDLIST\r\n"
    )


@dataclass
class FakeEmbyState:
    behavior: FakeEmbyBehavior = field(default_factory=FakeEmbyBehavior)
    requests: list[dict[str, Any]] = field(default_factory=list)
    search_items: list[dict[str, Any]] | None = None
    search_responses: dict[str, list[dict[str, Any]]] | None = None
    user_items: list[dict[str, Any]] | None = None
    stream_closed: asyncio.Event = field(default_factory=asyncio.Event)

    def record(self, request: Request, *, body: Any = None) -> None:
        row: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "query": list(request.query_params.multi_items()),
        }
        if body is not None:
            row["body"] = body
        self.requests.append(row)

    async def before(self, request: Request) -> Response | None:
        path = request.url.path
        delay = self.behavior.delays_ms.get(path, 0)
        if delay:
            await asyncio.sleep(delay / 1000)
        remaining = self.behavior.transient_failures.get(path, 0)
        if remaining > 0:
            self.behavior.transient_failures[path] = remaining - 1
            return Response(status_code=self.behavior.transient_status)
        return None


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="test controls are loopback-only")


def _filter_artifact(kind: str) -> dict[str, Any]:
    """Serve the captured catalogue with one known value pinned at the front.

    The known value is what tests select on. The rest of the artifact is kept
    rather than discarded: reducing every catalogue to a single row made the
    fake unable to express a filter control with more than one option, so
    nothing could detect a backend that dropped, truncated or mis-ordered the
    values it received.
    """
    artifact_name, value = _FILTER_ARTIFACT_NAMES[kind]
    payload = json.loads((_ARTIFACT_ROOT / f"{artifact_name}.json").read_text(encoding="utf-8"))
    result = copy.deepcopy(payload)
    items = list(result.get("Items") or [])
    if items:
        first = dict(items[0])
        first["Name"] = value
        items[0] = first
    else:
        items = [{"Name": value}]
    result["Items"] = items
    result["TotalRecordCount"] = len(items)
    return result


# Ids the captured corpus actually describes, plus the fake's own movie. A real
# Emby answers 404 for anything else; returning a fully-shaped payload for every
# id meant no test could detect a wrong or missing item id being sent upstream.
KNOWN_ITEM_IDS = {
    MOVIE["Id"],
    "movie-1",
    "episode-1",
    "series-1",
    "season-1",
    "playlist-1",
}


def _known_item(item_id: str) -> None:
    if item_id not in KNOWN_ITEM_IDS:
        raise HTTPException(status_code=404, detail="Item not found")


def create_fake_emby_app(state: FakeEmbyState | None = None) -> FastAPI:
    state = state or FakeEmbyState()
    app = FastAPI(title="Fake Emby", docs_url=None, redoc_url=None)
    app.state.fake_emby = state

    @app.middleware("http")
    async def _injected_behavior(request: Request, call_next):
        """Failure and delay injection for every upstream route, not five.

        This used to be an explicit call inside individual handlers, and it was
        wired into the five older endpoints and none of the library ones. Every
        upstream-failure path added by the library work was therefore
        unreachable from a test: the 502 mappings and the filter-option
        degradation could not be exercised even in principle.
        """
        is_upstream = not request.url.path.startswith("/__test__")
        if is_upstream and (failure := await state.before(request)):
            # The handler never runs, so it cannot record the attempt. Retry
            # tests count attempts, and a failed one still happened.
            state.record(request)
            return failure
        return await call_next(request)

    @app.get("/__test__/requests")
    async def recorded_requests(request: Request):
        _require_loopback(request)
        return {"requests": state.requests}

    @app.get("/__test__/state")
    async def observable_state(request: Request):
        _require_loopback(request)
        return {"stream_closed": state.stream_closed.is_set()}

    @app.post("/__test__/reset")
    async def reset(request: Request):
        _require_loopback(request)
        state.requests.clear()
        state.behavior = FakeEmbyBehavior()
        state.stream_closed = asyncio.Event()
        return {"success": True}

    @app.post("/__test__/behavior")
    async def configure_behavior(request: Request):
        _require_loopback(request)
        data = await request.json()
        state.behavior.delays_ms = dict(data.get("delays_ms", {}))
        state.behavior.transient_failures = dict(data.get("transient_failures", {}))
        state.behavior.transient_status = int(data.get("transient_status", 503))
        state.behavior.segment_delay_ms = int(data.get("segment_delay_ms", 0))
        if "master_playlist" in data:
            state.behavior.master_playlist = str(data["master_playlist"])
        if "variant_playlist" in data:
            state.behavior.variant_playlist = str(data["variant_playlist"])
        state.behavior.redirect_segments = bool(data.get("redirect_segments", False))
        return {"success": True}

    @app.get("/emby/System/Info/Public")
    async def system_info(request: Request):
        state.record(request)
        return {"ServerName": "Fake Emby", "Version": "4.9.0"}

    @app.post("/emby/Users/AuthenticateByName")
    async def authenticate(request: Request):
        credentials = await request.json()
        state.record(request)  # Never retain submitted credentials.
        username = credentials.get("Username")
        if username == "LargeLibrary":
            user_id = "user-large"
        elif username == "AlphabetLibrary":
            user_id = "user-alphabet"
        else:
            user_id = "user-1"
        return {
            "AccessToken": "fake-access-token",
            "User": {
                "Id": user_id,
                "Name": credentials.get("Username") or "Alice",
                "Policy": {"IsAdministrator": True},
            },
        }

    @app.post("/emby/Sessions/Capabilities/Full")
    async def capabilities(request: Request):
        state.record(request)
        return {}

    @app.get("/emby/Users/{user_id}")
    async def user(request: Request, user_id: str):
        state.record(request)
        return {"Id": user_id, "Name": "Alice"}

    @app.get("/emby/Users/{user_id}/Views")
    async def views(request: Request, user_id: str):
        del user_id
        state.record(request)
        return {
            "Items": [
                {
                    "Id": "library-1",
                    "Name": "Movies",
                    "Type": "CollectionFolder",
                    "CollectionType": "movies",
                },
                # A real deployment has more than one collection type, and the
                # scope resolvers behave differently per type. With only a
                # movies library present, a wrong Series scope was untestable.
                {
                    "Id": "library-2",
                    "Name": "TV Shows",
                    "Type": "CollectionFolder",
                    "CollectionType": "tvshows",
                },
            ],
            "TotalRecordCount": 2,
        }

    @app.get("/emby/Library/MediaFolders")
    async def media_folders(request: Request):
        state.record(request)
        return {
            "Items": [
                {"Id": "library-1", "Name": "Movies", "CollectionType": "movies"},
                {"Id": "library-2", "Name": "TV Shows", "CollectionType": "tvshows"},
            ]
        }

    @app.get("/emby/Items/Prefixes")
    async def item_prefixes(request: Request):
        state.record(request)
        return [
            {"Name": "#", "Value": None},
            {"Name": "A", "Value": None},
            {"Name": "M", "Value": None},
            {"Name": "Z", "Value": None},
        ]

    @app.get("/emby/Genres")
    @app.get("/emby/Studios")
    @app.get("/emby/Tags")
    @app.get("/emby/Years")
    @app.get("/emby/OfficialRatings")
    @app.get("/emby/Containers")
    @app.get("/emby/VideoCodecs")
    @app.get("/emby/AudioCodecs")
    @app.get("/emby/AudioLayouts")
    @app.get("/emby/SubtitleCodecs")
    async def filter_values(request: Request):
        state.record(request)
        return _filter_artifact(request.url.path.rsplit("/", 1)[-1])

    @app.get("/emby/Users/{user_id}/Items")
    async def user_items(request: Request, user_id: str):
        state.record(request)
        if request.query_params.get("IncludeItemTypes") == "Playlist":
            return {
                "Items": [{"Id": "playlist-1", "Name": "Watch later", "Type": "Playlist"}],
                "TotalRecordCount": 1,
            }
        search_term_raw = request.query_params.get("SearchTerm")
        if search_term_raw and state.search_responses is not None:
            items = copy.deepcopy(state.search_responses.get(search_term_raw.casefold(), []))
            return {"Items": items, "TotalRecordCount": len(items)}
        if search_term_raw and state.search_items is not None:
            return {
                "Items": copy.deepcopy(state.search_items),
                "TotalRecordCount": len(state.search_items),
            }
        if state.user_items is not None:
            return {
                "Items": copy.deepcopy(state.user_items),
                "TotalRecordCount": len(state.user_items),
            }
        if user_id not in {"user-large", "user-alphabet"}:
            return {"Items": [MOVIE], "TotalRecordCount": 1}

        if user_id == "user-alphabet":
            catalog: list[dict[str, Any]] = []
            for prefix, count in (
                ("# Feature", 25),
                ("Alpha Movie", 75),
                ("Middle Movie", 150),
                ("Zulu Movie", 150),
            ):
                for index in range(count):
                    name = f"{prefix} {index:04d}"
                    catalog.append(
                        {
                            **MOVIE,
                            "Id": f"alphabet-{len(catalog):04d}",
                            "Name": name,
                            "SortName": name,
                        }
                    )
        else:
            catalog = [
                {
                    **MOVIE,
                    "Id": f"large-{index:04d}",
                    "Name": f"Large Movie {index:04d}",
                }
                for index in range(500)
            ]
        search_term = request.query_params.get("SearchTerm", "").casefold()
        if search_term:
            catalog = [item for item in catalog if search_term in item["Name"].casefold()]
        name_less_than = request.query_params.get("NameLessThan")
        if name_less_than:
            boundary = name_less_than.casefold()
            preceding = [
                item for item in catalog if item.get("SortName", item["Name"]).casefold() < boundary
            ]
            return {"Items": preceding[:1], "TotalRecordCount": len(preceding)}
        start = int(request.query_params.get("StartIndex", 0))
        limit = int(request.query_params.get("Limit", len(catalog)))
        return {
            "Items": catalog[start : start + limit],
            "TotalRecordCount": len(catalog),
        }

    @app.get("/emby/Items")
    async def items(request: Request):
        state.record(request)
        return {"Items": [MOVIE], "TotalRecordCount": 1}

    @app.api_route("/emby/Users/{user_id}/FavoriteItems/{item_id}", methods=["POST", "DELETE"])
    async def favorite_item(request: Request, user_id: str, item_id: str):
        del user_id
        _known_item(item_id)
        state.record(request)
        return {"IsFavorite": request.method == "POST"}

    @app.api_route("/emby/Users/{user_id}/PlayedItems/{item_id}", methods=["POST", "DELETE"])
    async def played_item(request: Request, user_id: str, item_id: str):
        del user_id
        _known_item(item_id)
        state.record(request)
        return {"Played": request.method == "POST"}

    @app.post("/emby/Playlists")
    async def create_playlist(request: Request):
        state.record(request)
        return {"Id": "playlist-2"}

    @app.post("/emby/Playlists/{playlist_id}/Items")
    async def add_playlist_item(request: Request, playlist_id: str):
        del playlist_id
        state.record(request)
        return {}

    @app.get("/emby/Items/{item_id}/Images/{image_type}")
    @app.get("/emby/Items/{item_id}/Images/{image_type}/{image_index}")
    async def item_image(
        request: Request, item_id: str, image_type: str, image_index: str | None = None
    ):
        """Artwork bytes. The fake had no route here at all, so /api/image
        answered 404 in every pytest and Playwright run and the proxy had no
        executable coverage: neither its bounds nor its auth were exercised."""
        _known_item(item_id)
        state.record(request)
        if image_type not in {"Primary", "Backdrop", "Logo", "Thumb", "Art", "Banner"}:
            raise HTTPException(status_code=404, detail="No such image type")
        if image_index is not None and not image_index.isdigit():
            raise HTTPException(status_code=404, detail="No such image index")
        # A real 1x1 PNG, enough to prove bytes and content-type round-trip.
        return Response(content=_PIXEL_PNG, media_type="image/png")

    @app.get("/emby/Items/{item_id}/Similar")
    async def similar_items(request: Request, item_id: str):
        _known_item(item_id)
        state.record(request)
        return json.loads((_ARTIFACT_ROOT / "related-items.json").read_text(encoding="utf-8"))

    @app.get("/emby/Shows/{series_id}/Seasons")
    async def show_seasons(request: Request, series_id: str):
        del series_id
        state.record(request)
        return json.loads((_ARTIFACT_ROOT / "seasons.json").read_text(encoding="utf-8"))

    @app.get("/emby/Shows/{series_id}/Episodes")
    async def show_episodes(request: Request, series_id: str):
        del series_id
        state.record(request)
        return json.loads((_ARTIFACT_ROOT / "episodes.json").read_text(encoding="utf-8"))

    @app.get("/emby/Users/{user_id}/Items/{item_id}/LocalTrailers")
    async def local_trailers(request: Request, user_id: str, item_id: str):
        del user_id
        _known_item(item_id)
        state.record(request)
        return json.loads((_ARTIFACT_ROOT / "trailers.json").read_text(encoding="utf-8"))

    @app.get("/emby/Users/{user_id}/Items/{item_id}/SpecialFeatures")
    async def special_features(request: Request, user_id: str, item_id: str):
        del user_id
        _known_item(item_id)
        state.record(request)
        return json.loads((_ARTIFACT_ROOT / "extras.json").read_text(encoding="utf-8"))

    @app.get("/emby/Items/Intros")
    async def intros(request: Request):
        state.record(request)
        return [{"Id": "movie-1", "Start": 0, "End": 30_000_000}]

    @app.get("/emby/Users/{user_id}/Items/{item_id}")
    async def user_item(request: Request, user_id: str, item_id: str):
        del user_id
        state.record(request)
        return {**MOVIE, "Id": item_id}

    @app.get("/emby/Items/{item_id}")
    async def item(request: Request, item_id: str):
        state.record(request)
        return {**MOVIE, "Id": item_id}

    @app.post("/emby/Items/{item_id}/PlaybackInfo")
    async def playback_info(request: Request, item_id: str):
        state.record(request, body=await request.json())
        return {
            "PlaySessionId": "play-session-1",
            "MediaSources": [{**MOVIE["MediaSources"][0], "ItemId": item_id}],
        }

    @app.get("/emby/Videos/{item_id}/{source_id}/Subtitles/{index}/Stream.vtt")
    async def subtitle_stream(request: Request, item_id: str, source_id: str, index: int):
        state.record(request)
        # Discarding the path parameters made this endpoint answer WEBVTT to
        # any item, any source and any stream index, so a proxy that dropped
        # or mangled them still looked correct. Real Emby 404s instead.
        subtitle_indices = {
            stream["Index"]
            for stream in MOVIE["MediaSources"][0]["MediaStreams"]
            if stream["Type"] == "Subtitle"
        }
        if (
            item_id != MOVIE["Id"]
            or source_id != MOVIE["MediaSources"][0]["Id"]
            or index not in subtitle_indices
        ):
            return Response(status_code=404)
        return Response(
            content="WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nFake subtitle\n",
            media_type="text/vtt",
        )

    @app.api_route("/emby/Sessions/Playing{suffix:path}", methods=["POST"])
    async def playback_report(request: Request, suffix: str):
        del suffix
        state.record(request, body=await request.json())
        return {}

    @app.delete("/emby/Videos/ActiveEncodings")
    async def stop_transcode(request: Request):
        state.record(request)
        return Response(status_code=204)

    @app.get("/emby/Videos/{item_id}/master.m3u8")
    async def master_playlist(request: Request, item_id: str):
        del item_id
        state.record(request)
        return Response(
            content=state.behavior.master_playlist,
            media_type="application/vnd.apple.mpegurl",
        )

    @app.get("/emby/Videos/{item_id}/main.m3u8")
    async def variant_playlist(request: Request, item_id: str):
        del item_id
        state.record(request)
        return Response(
            content=state.behavior.variant_playlist,
            media_type="application/vnd.apple.mpegurl",
        )

    @app.get("/emby/Videos/{item_id}/{segment_name}")
    async def segment(request: Request, item_id: str, segment_name: str):
        del item_id
        state.record(request)

        # Emby runs on ASP.NET, whose route matching is case-insensitive,
        # so `main.M3U8` returns the variant playlist rather than falling
        # through to segment bytes. Reproduced here because the proxy has
        # to handle an uppercase extension the same way it handles a
        # lowercase one; with this route case-sensitive, a proxy that
        # streamed the raw upstream body looked harmless in tests.
        if segment_name.lower().endswith(".m3u8"):
            return Response(
                content=state.behavior.variant_playlist,
                media_type="application/vnd.apple.mpegurl",
            )

        if state.behavior.redirect_segments:
            return Response(
                status_code=302,
                headers={"Location": "http://emby.internal/relocated/segment0.ts"},
            )

        chunks = state.behavior.segment_chunks
        range_header = request.headers.get("range")
        range_start = 0
        range_end = len(_SEGMENT_BYTES) - 1
        if range_header and range_header.startswith("bytes="):
            start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
            range_start = int(start_text or 0)
            # A real server refuses a range that starts past the end, and
            # RFC 7233 requires the 416 to carry the true length so the
            # client can retry. The proxy used to drop that header because
            # it only copied range metadata on 206.
            if range_start >= len(_SEGMENT_BYTES):
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{len(_SEGMENT_BYTES)}"},
                )
            range_end = min(int(end_text or range_end), range_end)
            ranged = b"".join(chunks)[range_start : range_end + 1]
            chunks = [ranged]

        async def body() -> AsyncIterator[bytes]:
            try:
                for chunk in chunks:
                    yield chunk
                    if state.behavior.segment_delay_ms:
                        await asyncio.sleep(state.behavior.segment_delay_ms / 1000)
            finally:
                state.stream_closed.set()

        headers: dict[str, str] = {"Accept-Ranges": "bytes"}
        status = 200
        if range_header:
            status = 206
            headers["Content-Range"] = f"bytes {range_start}-{range_end}/{len(_SEGMENT_BYTES)}"
            headers["Content-Length"] = str(range_end - range_start + 1)
        return StreamingResponse(
            body(), status_code=status, media_type="video/MP2T", headers=headers
        )

    return app
