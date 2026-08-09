"""Capture shape-preserving, privacy-safe contracts from a real Emby server.

Raw responses never touch disk. Only their SHA-256 and sanitized JSON are saved.
"""

from __future__ import annotations

import hashlib
import json
import re
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
                "movie-items",
                "GET",
                "/emby/Users/{user_id}/Items",
                movie_items_response,
            ),
            (
                "movie-detail",
                "GET",
                "/emby/Users/{user_id}/Items/{item_id}",
                client.get(f"/emby/Users/{user_id}/Items/{movie['Id']}", params={"Fields": fields}),
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
            episodes_response = client.get(
                f"/emby/Shows/{series['Id']}/Episodes",
                params={"UserId": user_id, "Fields": fields, "Limit": 1},
            )
            episodes_response.raise_for_status()
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

        OUTPUT.mkdir(parents=True, exist_ok=True)
        for boundary, method, path, response in captures:
            response.raise_for_status()
            raw = response.content
            sanitized = sanitizer.value(response.json())
            rendered = _canonical(sanitized)
            filename = f"{boundary}.json"
            (OUTPUT / filename).write_bytes(rendered)
            manifest_rows.append(
                {
                    "boundary": boundary,
                    "file": filename,
                    "method": method,
                    "path": path,
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
