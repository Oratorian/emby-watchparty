"""Capture shape-preserving, privacy-safe contracts from a real Emby server.

Raw responses never touch disk. Only their SHA-256 and sanitized JSON are saved.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "artifacts" / "emby" / "4.9.5.0"
PRIVATE_KEY_PARTS = ("token", "password", "path", "username", "providerid")
SEMANTIC_STRINGS = {
    "Type",
    "MediaType",
    "CollectionType",
    "Container",
    "Codec",
    "Language",
    "DisplayTitle",
    "VideoType",
    "Video3DFormat",
    "OfficialRating",
    "Status",
}


def _dotenv() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


class Sanitizer:
    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.names: dict[str, str] = {}

    def _mapped(self, value: str, table: dict[str, str], prefix: str) -> str:
        if value not in table:
            table[value] = f"<{prefix}-{len(table) + 1:03d}>"
        return table[value]

    def value(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: self.value(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item, key) for item in value]
        if not isinstance(value, str):
            return value

        lowered = key.casefold()
        if any(part in lowered for part in PRIVATE_KEY_PARTS):
            return f"<{re.sub(r'[^a-z0-9]+', '-', lowered).strip('-') or 'private'}>"
        if key == "Id" or lowered.endswith(("id", "ids")):
            return self._mapped(value, self.ids, "id")
        if key in SEMANTIC_STRINGS:
            return value
        if key in {"Name", "OriginalTitle", "SeriesName", "Album", "Tagline", "Overview"}:
            return self._mapped(value, self.names, "text")
        if value.startswith(("http://", "https://")):
            return "<url>"
        if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\")):
            return "<path>"
        return value


def _canonical(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _request_provenance(response: httpx.Response, sanitizer: Sanitizer) -> dict[str, Any]:
    query = dict(response.request.url.params.multi_items())
    body: Any = None
    if response.request.content:
        try:
            body = json.loads(response.request.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = "<non-json-body>"
    return {
        "query": sanitizer.value(query),
        "body": sanitizer.value(body),
    }


def main() -> None:
    env = _dotenv()
    server = env.get("EMBY_SERVER_URL", "http://127.0.0.1:8096").rstrip("/")
    token = env["EMBY_API_KEY"]
    sanitizer = Sanitizer()
    manifest_rows: list[dict[str, Any]] = []

    with httpx.Client(base_url=server, headers={"X-Emby-Token": token}, timeout=30) as client:
        users_response = client.get("/emby/Users")
        users_response.raise_for_status()
        users = users_response.json()
        if not users:
            raise RuntimeError("real Emby harness has no users")
        user_id = users[0]["Id"]

        views_response = client.get(f"/emby/Users/{user_id}/Views")
        views_response.raise_for_status()
        views = views_response.json()
        movie_view = next(
            item for item in views["Items"] if item.get("CollectionType") == "movies"
        )
        tv_view = next(
            (item for item in views["Items"] if item.get("CollectionType") == "tvshows"),
            None,
        )

        fields = (
            "Overview,PrimaryImageAspectRatio,ProductionYear,UserData,RunTimeTicks,"
            "MediaSources,MediaStreams,People,Genres,Studios,Tags,ProviderIds,Taglines,"
            "BackdropImageTags,LogoImageTag,CommunityRating,CriticRating,OfficialRating"
        )
        movie_items_response = client.get(
            f"/emby/Users/{user_id}/Items",
            params={
                "ParentId": movie_view["Id"],
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "Fields": fields,
                "Limit": 3,
            },
        )
        movie_items_response.raise_for_status()
        movie_items = movie_items_response.json()
        movie = movie_items["Items"][0]

        captures: list[tuple[str, str, str, httpx.Response]] = [
            (
                "system-info",
                "GET",
                "/emby/System/Info/Public",
                client.get("/emby/System/Info/Public"),
            ),
            ("libraries", "GET", "/emby/Users/{user_id}/Views", views_response),
            (
                "filter-options",
                "GET",
                "/emby/Genres",
                client.get(
                    "/emby/Genres",
                    params={
                        "UserId": user_id,
                        "ParentId": movie_view["Id"],
                        "IncludeItemTypes": "Movie",
                        "Recursive": "true",
                        "Limit": 50,
                    },
                ),
            ),
            (
                "upstream-error",
                "GET",
                "/emby/Items/Filters",
                client.get(
                    "/emby/Items/Filters",
                    params={"UserId": user_id, "ParentId": movie_view["Id"]},
                ),
            ),
            (
                "movie-items",
                "GET",
                "/emby/Users/{user_id}/Items",
                movie_items_response,
            ),
            (
                "resolution-filter",
                "GET",
                "/emby/Users/{user_id}/Items?MinHeight=1080&MaxHeight=2159",
                client.get(
                    f"/emby/Users/{user_id}/Items",
                    params={
                        "ParentId": movie_view["Id"],
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie",
                        "MinHeight": 1080,
                        "MaxHeight": 2159,
                        "Limit": 3,
                    },
                ),
            ),
            (
                "filtered-prefixes",
                "GET",
                "/emby/Items/Prefixes?Filters=IsResumable",
                client.get(
                    "/emby/Items/Prefixes",
                    params={
                        "UserId": user_id,
                        "ParentId": movie_view["Id"],
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie",
                        "Filters": "IsResumable",
                        "SortBy": "SortName",
                        "SortOrder": "Ascending",
                    },
                ),
            ),
            (
                "movie-detail",
                "GET",
                "/emby/Users/{user_id}/Items/{item_id}",
                client.get(f"/emby/Users/{user_id}/Items/{movie['Id']}", params={"Fields": fields}),
            ),
            (
                "playback-selection",
                "POST",
                "/emby/Items/{item_id}/PlaybackInfo",
                client.post(
                    f"/emby/Items/{movie['Id']}/PlaybackInfo",
                    params={
                        "UserId": user_id,
                        "IsPlayback": "true",
                        "AutoOpenLiveStream": "true",
                        "StartTimeTicks": 0,
                    },
                    json={},
                ),
            ),
            (
                "related-items",
                "GET",
                "/emby/Items/{item_id}/Similar",
                client.get(
                    f"/emby/Items/{movie['Id']}/Similar",
                    params={"UserId": user_id, "Fields": fields, "Limit": 12},
                ),
            ),
            (
                "trailers",
                "GET",
                "/emby/Users/{user_id}/Items/{item_id}/LocalTrailers",
                client.get(f"/emby/Users/{user_id}/Items/{movie['Id']}/LocalTrailers"),
            ),
            (
                "extras",
                "GET",
                "/emby/Users/{user_id}/Items/{item_id}/SpecialFeatures",
                client.get(f"/emby/Users/{user_id}/Items/{movie['Id']}/SpecialFeatures"),
            ),
            (
                "grouped-search-source",
                "GET",
                "/emby/Users/{user_id}/Items?SearchTerm={sanitized}",
                client.get(
                    f"/emby/Users/{user_id}/Items",
                    params={
                        "SearchTerm": movie["Name"],
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie,Series,Episode,Person,BoxSet",
                        "Fields": fields,
                        "Limit": 20,
                    },
                ),
            ),
            (
                "playlists",
                "GET",
                "/emby/Users/{user_id}/Items?IncludeItemTypes=Playlist",
                client.get(
                    f"/emby/Users/{user_id}/Items",
                    params={"Recursive": "true", "IncludeItemTypes": "Playlist", "Fields": fields},
                ),
            ),
        ]

        for endpoint, boundary in (
            ("/emby/Genres", "genres"),
            ("/emby/Studios", "studios"),
            ("/emby/Tags", "tags"),
            ("/emby/Years", "years"),
            ("/emby/VideoCodecs", "video-codecs"),
            ("/emby/AudioCodecs", "audio-codecs"),
            ("/emby/Containers", "containers"),
            ("/emby/AudioLayouts", "audio-layouts"),
            ("/emby/SubtitleCodecs", "subtitle-codecs"),
            ("/emby/OfficialRatings", "official-ratings"),
        ):
            response = client.get(
                endpoint,
                params={
                    "UserId": user_id,
                    "ParentId": movie_view["Id"],
                    "IncludeItemTypes": "Movie",
                    "Recursive": "true",
                    "Limit": 50,
                },
            )
            if response.status_code < 400:
                captures.append((boundary, "GET", endpoint, response))

        if tv_view:
            series_response = client.get(
                f"/emby/Users/{user_id}/Items",
                params={
                    "ParentId": tv_view["Id"],
                    "Recursive": "true",
                    "IncludeItemTypes": "Series",
                    "Fields": fields,
                    "Limit": 1,
                },
            )
            series_response.raise_for_status()
            series = series_response.json()["Items"][0]
            series_detail = client.get(
                f"/emby/Users/{user_id}/Items/{series['Id']}", params={"Fields": fields}
            )
            captures.append(
                ("series-detail", "GET", "/emby/Users/{user_id}/Items/{series_id}", series_detail)
            )
            seasons_response = client.get(
                f"/emby/Shows/{series['Id']}/Seasons",
                params={"UserId": user_id, "Fields": fields},
            )
            seasons_response.raise_for_status()
            captures.append(
                ("seasons", "GET", "/emby/Shows/{series_id}/Seasons", seasons_response)
            )
            episodes_response = client.get(
                f"/emby/Shows/{series['Id']}/Episodes",
                params={"UserId": user_id, "Fields": fields, "Limit": 1},
            )
            episodes_response.raise_for_status()
            captures.append(
                ("episodes", "GET", "/emby/Shows/{series_id}/Episodes", episodes_response)
            )
            episode = episodes_response.json()["Items"][0]
            captures.append(
                (
                    "episode-detail",
                    "GET",
                    "/emby/Users/{user_id}/Items/{episode_id}",
                    client.get(
                        f"/emby/Users/{user_id}/Items/{episode['Id']}", params={"Fields": fields}
                    ),
                )
            )
        else:
            captures.extend(
                [
                    ("series-detail", "GET", "/emby/Users/{user_id}/Items/{series_id}", views_response),
                    ("episode-detail", "GET", "/emby/Users/{user_id}/Items/{episode_id}", views_response),
                ]
            )

        user_data = movie.get("UserData") or {}
        favorite_path = f"/emby/Users/{user_id}/FavoriteItems/{movie['Id']}"
        favorite_add = client.post(favorite_path)
        favorite_remove = client.delete(favorite_path)
        if user_data.get("IsFavorite"):
            # Restore the original favorite state after observing both methods.
            client.post(favorite_path).raise_for_status()
        captures.extend(
            [
                ("favorite-add", "POST", "/emby/Users/{user_id}/FavoriteItems/{item_id}", favorite_add),
                ("favorite-remove", "DELETE", "/emby/Users/{user_id}/FavoriteItems/{item_id}", favorite_remove),
            ]
        )

        played_path = f"/emby/Users/{user_id}/PlayedItems/{movie['Id']}"
        played_add = client.post(played_path)
        played_remove = client.delete(played_path)
        if user_data.get("Played"):
            # Restore the original played state after observing both methods.
            client.post(played_path).raise_for_status()
        captures.extend(
            [
                ("played-add", "POST", "/emby/Users/{user_id}/PlayedItems/{item_id}", played_add),
                ("played-remove", "DELETE", "/emby/Users/{user_id}/PlayedItems/{item_id}", played_remove),
            ]
        )

        temporary_name = f"contract-capture-{uuid.uuid4().hex}"
        playlist_create = client.post(
            "/emby/Playlists",
            params={"Name": temporary_name, "UserId": user_id},
        )
        playlist_create.raise_for_status()
        playlist_id = playlist_create.json()["Id"]
        try:
            playlist_add = client.post(
                f"/emby/Playlists/{playlist_id}/Items",
                params={"Ids": movie["Id"], "UserId": user_id},
            )
            playlist_add.raise_for_status()
            captures.extend(
                [
                    ("playlist-create", "POST", "/emby/Playlists", playlist_create),
                    (
                        "playlist-add",
                        "POST",
                        "/emby/Playlists/{playlist_id}/Items",
                        playlist_add,
                    ),
                ]
            )
        finally:
            client.delete(f"/emby/Items/{playlist_id}").raise_for_status()

        OUTPUT.mkdir(parents=True, exist_ok=True)
        for boundary, method, path, response in captures:
            raw = response.content
            if raw:
                try:
                    response_payload = response.json()
                except json.JSONDecodeError:
                    response_payload = {
                        "NonJsonBody": True,
                        "ContentType": response.headers.get("Content-Type", ""),
                    }
            else:
                response_payload = {}
            sanitized = sanitizer.value(response_payload)
            rendered = _canonical(sanitized)
            filename = f"{boundary}.json"
            (OUTPUT / filename).write_bytes(rendered)
            manifest_rows.append(
                {
                    "boundary": boundary,
                    "file": filename,
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "request": _request_provenance(response, sanitizer),
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "sanitized_sha256": hashlib.sha256(rendered).hexdigest(),
                }
            )

    manifest = {
        "captured_at": datetime.now(UTC).isoformat(),
        "emby_version": "4.9.5.0",
        "sanitization": "shape-preserving-v1",
        "artifacts": manifest_rows,
    }
    (OUTPUT / "manifest.json").write_bytes(_canonical(manifest))


if __name__ == "__main__":
    main()
