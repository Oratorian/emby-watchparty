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


def test_grouped_search_normalizes_supported_emby_item_types(live_watchparty) -> None:
    live_watchparty.fake.state.search_items = [
        {"Id": "movie-1", "Name": "Matrix", "Type": "Movie"},
        {"Id": "series-1", "Name": "Matrix TV", "Type": "Series"},
        {"Id": "episode-1", "Name": "Pilot", "Type": "Episode"},
        {"Id": "person-1", "Name": "Actor", "Type": "Person"},
        {"Id": "box-1", "Name": "Matrix Collection", "Type": "BoxSet"},
    ]
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/search/grouped", params={"q": "matrix"})
    finally:
        client.close()

    assert response.status_code == 200
    groups = {group["id"]: group["items"] for group in response.json()["groups"]}
    assert [item["Id"] for item in groups["movies"]] == ["movie-1"]
    assert [item["Id"] for item in groups["series"]] == ["series-1"]
    assert [item["Id"] for item in groups["episodes"]] == ["episode-1"]
    assert [item["Id"] for item in groups["people"]] == ["person-1"]
    assert [item["Id"] for item in groups["collections"]] == ["box-1"]
    upstream = live_watchparty.fake.state.requests[-1]
    assert ("SearchTerm", "matrix") in upstream["query"]
    assert (
        "IncludeItemTypes",
        "Movie,Series,Episode,Person,BoxSet",
    ) in upstream["query"]


def test_detail_sections_proxy_artifact_observed_boundaries(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        responses = {
            section: client.get(f"/api/item/movie-1/sections/{section}")
            for section in ("related", "trailers", "extras")
        }
    finally:
        client.close()

    assert all(response.status_code == 200 for response in responses.values())
    assert all("items" in response.json() for response in responses.values())
    paths = {row["path"] for row in live_watchparty.fake.state.requests}
    assert "/emby/Items/movie-1/Similar" in paths
    assert "/emby/Users/user-1/Items/movie-1/LocalTrailers" in paths
    assert "/emby/Users/user-1/Items/movie-1/SpecialFeatures" in paths


def test_personal_actions_are_host_only_and_match_real_requests(live_watchparty) -> None:
    host = httpx.Client(base_url=live_watchparty.url)
    party_id = host.post("/api/party/create", json={}).json()["party_id"]
    host.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "host-client", "display_name": "Host"},
    ).raise_for_status()
    host.post(
        "/api/auth/login", json={"username": "Host", "password": "password"}
    ).raise_for_status()
    guest = httpx.Client(base_url=live_watchparty.url)
    guest.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "guest-client", "display_name": "Guest"},
    ).raise_for_status()
    try:
        assert host.put("/api/item/movie-1/favorite", json={"favorite": True}).json() == {
            "success": True,
            "favorite": True,
        }
        assert host.put("/api/item/movie-1/played", json={"played": False}).json() == {
            "success": True,
            "played": False,
        }
        assert host.get("/api/playlists").json()["items"][0]["Id"] == "playlist-1"
        created = host.post("/api/playlists", json={"name": "Party picks"})
        assert created.json() == {"id": "playlist-2", "name": "Party picks"}
        added = host.post(
            "/api/playlists/playlist-2/items", json={"item_id": "movie-1"}
        )
        assert added.json() == {"success": True}
        assert guest.put(
            "/api/item/movie-1/favorite", json={"favorite": True}
        ).status_code == 403
    finally:
        host.close()
        guest.close()

    requests = live_watchparty.fake.state.requests
    assert any(row["method"] == "POST" and row["path"].endswith("/FavoriteItems/movie-1") for row in requests)
    assert any(row["method"] == "DELETE" and row["path"].endswith("/PlayedItems/movie-1") for row in requests)
    assert any(
        row["path"] == "/emby/Playlists"
        and ("Name", "Party picks") in row["query"]
        and ("UserId", "user-1") in row["query"]
        for row in requests
    )
    assert any(
        row["path"] == "/emby/Playlists/playlist-2/Items"
        and ("Ids", "movie-1") in row["query"]
        for row in requests
    )


def test_series_sections_use_observed_season_and_episode_endpoints(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        seasons = client.get("/api/item/series-1/seasons")
        episodes = client.get(
            "/api/item/series-1/episodes", params={"seasonId": "season-1"}
        )
    finally:
        client.close()

    assert seasons.status_code == 200
    assert episodes.status_code == 200
    assert "items" in seasons.json()
    assert "items" in episodes.json()
    requests = live_watchparty.fake.state.requests
    assert any(row["path"] == "/emby/Shows/series-1/Seasons" for row in requests)
    assert any(
        row["path"] == "/emby/Shows/series-1/Episodes"
        and ("SeasonId", "season-1") in row["query"]
        for row in requests
    )
