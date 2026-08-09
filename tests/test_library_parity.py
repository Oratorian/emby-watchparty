from __future__ import annotations

import httpx


def _unlocked_client(live_watchparty) -> httpx.Client:
    client = httpx.Client(base_url=live_watchparty.url)
    party_id = client.post("/api/party/create", json={}).json()["party_id"]
    client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "parity-client", "display_name": "Alice"},
    ).raise_for_status()
    client.post(
        "/api/auth/login",
        json={"username": "Alice", "password": "password"},
    ).raise_for_status()
    return client


def test_library_query_maps_viewer_filters_to_emby(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/items/query",
            json={
                "scope": {
                    "parent_id": "library-1",
                    "include_item_types": ["Movie"],
                    "media_types": ["Video"],
                    "recursive": True,
                },
                "page": {"start_index": 10, "limit": 25},
                "sort": {"field": "ProductionYear", "direction": "Descending"},
                "filters": {
                    "playstate": "resumable",
                    "favorite": True,
                    "duplicates": True,
                    "genres": ["Drama"],
                    "official_ratings": ["PG-13"],
                    "studios": ["Studio A"],
                    "tags": ["Featured"],
                    "years": [2024],
                    "containers": ["mkv"],
                    "video_codecs": ["h264"],
                    "video_types": ["VideoFile"],
                    "is_3d": True,
                    "audio_codecs": ["aac"],
                    "audio_layouts": ["stereo"],
                    "audio_languages": ["eng"],
                    "subtitles": "with",
                    "subtitle_codecs": ["subrip"],
                    "subtitle_languages": ["eng"],
                    "trailers": "with",
                    "extras": "without",
                    "theme_songs": "with",
                    "theme_videos": "without",
                    "locked": "yes",
                    "overview": "with",
                    "missing_provider_ids": ["imdb", "tmdb"],
                },
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    upstream = next(row for row in recorded if row["path"].endswith("/Items"))
    query = dict(upstream["query"])
    assert query == {
        "AudioCodecs": "aac",
        "AudioLanguages": "eng",
        "AudioLayouts": "stereo",
        "Containers": "mkv",
        "Fields": (
            "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,"
            "ParentIndexNumber,SeriesId,SeasonId,UserData,MediaSourceCount"
        ),
        "Filters": "IsResumable",
        "Genres": "Drama",
        "HasImdbId": "false",
        "HasOverview": "true",
        "HasSpecialFeature": "false",
        "HasSubtitles": "true",
        "HasThemeSong": "true",
        "HasThemeVideo": "false",
        "HasTmdbId": "false",
        "HasTrailer": "true",
        "IncludeItemTypes": "Movie",
        "Is3D": "true",
        "IsDuplicate": "true",
        "IsFavorite": "true",
        "IsLocked": "true",
        "Limit": "25",
        "MediaTypes": "Video",
        "OfficialRatings": "PG-13",
        "ParentId": "library-1",
        "Recursive": "true",
        "SortBy": "ProductionYear",
        "SortOrder": "Descending",
        "StartIndex": "10",
        "Studios": "Studio A",
        "SubtitleCodecs": "subrip",
        "SubtitleLanguages": "eng",
        "Tags": "Featured",
        "VideoCodecs": "h264",
        "VideoTypes": "VideoFile",
        "Years": "2024",
    }


def test_filter_options_are_capability_driven_from_emby(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(
            "/api/items/filter-options",
            params={
                "parentId": "library-1",
                "includeItemTypes": "Movie",
                "mediaTypes": "Video",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    controls = {control["id"]: control for control in response.json()["controls"]}
    assert controls["playstate"]["values"] == [
        {"value": "any", "label": "Any"},
        {"value": "unplayed", "label": "Unplayed"},
        {"value": "played", "label": "Played"},
        {"value": "resumable", "label": "In progress"},
    ]
    assert controls["genre"]["values"] == [{"value": "Drama", "label": "Drama"}]
    assert controls["container"]["values"] == [{"value": "mkv", "label": "MKV"}]
    assert controls["video_codec"]["values"] == [{"value": "h264", "label": "H264"}]
    assert controls["audio_codec"]["values"] == [{"value": "aac", "label": "AAC"}]
    assert controls["subtitle_codec"]["values"] == [
        {"value": "subrip", "label": "SUBRIP"}
    ]
    assert "audio_language" not in controls

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    option_paths = {row["path"] for row in recorded}
    assert {
        "/emby/Genres",
        "/emby/Studios",
        "/emby/Tags",
        "/emby/Years",
        "/emby/OfficialRatings",
        "/emby/Containers",
        "/emby/VideoCodecs",
        "/emby/AudioCodecs",
        "/emby/AudioLayouts",
        "/emby/SubtitleCodecs",
    } <= option_paths
