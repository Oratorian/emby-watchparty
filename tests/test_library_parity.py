"""What the Emby adapter puts on the wire, checked against a live fake server.

This file was written to prove the v1 library routes and their v2 twins agreed.
There is only one side now, so each test asserts the surviving side directly:
the request /api/v2 sends upstream, and the response it hands the viewer.

The assertions are about the upstream call as much as the JSON, because the
fake is permissive where a real Emby is not. A filter that never reaches the
query string still returns a plausible page here.
"""

from __future__ import annotations

from typing import Literal, get_args, get_origin

import httpx

from backend.src.v2_schemas import CatalogFiltersV2

# Every filter CatalogFiltersV2 accepts, mapped to the control id that lets a
# viewer set it. This is the only hand-written half, and it is guarded: the
# test below fails when a field exists in the schema and not in here, so
# adding a filter forces an explicit decision about how it is reached.
#
# None means "deliberately not on the rail", with the reason, because silence
# is what let eleven of these go missing for a release.
FILTER_FIELD_TO_CONTROL: dict[str, str | None] = {
    "playstate": "playstate",
    "favorite": "favorite",
    "duplicates": "duplicates",
    "genres": "genre",
    "official_ratings": "official_rating",
    "studios": "studio",
    "tags": "tag",
    "years": "year",
    "community_rating_min": "community_rating",
    "critic_rating_min": "critic_rating",
    "containers": "container",
    "video_codecs": "video_codec",
    "video_types": "video_type",
    "resolutions": "resolution",
    "is_3d": "is_3d",
    "audio_codecs": "audio_codec",
    "audio_layouts": "audio_layout",
    "subtitles": "subtitles",
    "subtitle_codecs": "subtitle_codec",
    "trailers": "trailers",
    "extras": "extras",
    "theme_songs": "theme_songs",
    "theme_videos": "theme_videos",
    "locked": "locked",
    "overview": "overview",
    "missing_provider_ids": "missing_provider_ids",
    # Set by clicking a name in the details view, not from the filter rail.
    "person_ids": None,
    # No catalogue endpoint backs these, so there is nothing to populate a
    # control with. The query side still accepts them for a caller that knows
    # the tag it wants.
    "audio_languages": None,
    "subtitle_languages": None,
}


def _closed_vocabularies() -> dict[str, str]:
    """Control id -> filter field, for every filter with a fixed set of tokens.

    Derived rather than listed. A closed vocabulary is exactly a field whose
    annotation is a Literal, so asking the schema is both the definition and
    the answer; the previous hand-written copy could omit a filter and the
    check would simply not run for it.

    These are the ones that matter because a control offering a token the
    query side does not accept produces a filter the viewer can select and the
    server then rejects with a 422.
    """
    closed: dict[str, str] = {}
    for field_name, control_id in FILTER_FIELD_TO_CONTROL.items():
        if control_id is None:
            continue
        annotation = CatalogFiltersV2.model_fields[field_name].annotation
        if get_origin(annotation) is list:
            annotation = get_args(annotation)[0]
        if get_origin(annotation) is Literal:
            closed[control_id] = field_name
    return closed


def _accepted_tokens(field_name: str) -> set[str]:
    """The literal values CatalogFiltersV2 will accept for a filter."""
    annotation = CatalogFiltersV2.model_fields[field_name].annotation
    if get_origin(annotation) is list:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) is Literal:
        return set(get_args(annotation))
    raise AssertionError(f"{field_name} is not a closed vocabulary any more")


def _unlocked_client(live_watchparty) -> httpx.Client:
    client = httpx.Client(base_url=live_watchparty.url)
    party_id = client.post("/api/party/create", json={}).json()["party_id"]
    client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "parity-client", "display_name": "Alice"},
    ).raise_for_status()
    client.post(
        "/api/v2/auth/login",
        json={"username": "Alice", "password": "password"},
    ).raise_for_status()
    return client


def test_library_query_maps_viewer_filters_to_emby(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/query",
            json={
                "scope": {
                    "parent_id": "library-1",
                    "include_kinds": ["movie"],
                    "media_kinds": ["video"],
                    "recursive": True,
                },
                "page": {"start": 10, "limit": 25},
                "sort": {"field": "year", "direction": "descending"},
                "filters": {
                    "playstate": "resumable",
                    "favorite": True,
                    "duplicates": True,
                    "genres": ["Drama"],
                    "official_ratings": ["PG-13"],
                    "studios": ["Studio A"],
                    "tags": ["Featured"],
                    "person_ids": ["person-1"],
                    "years": [2024],
                    "containers": ["mkv"],
                    "video_codecs": ["h264"],
                    "video_types": ["VideoFile"],
                    "resolutions": ["1080p"],
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
    # Fields is asserted separately: which metadata a page asks for is a
    # payload-size decision that moves, while every entry below is a filter a
    # viewer set and must therefore reach Emby exactly as sent.
    fields = query.pop("Fields")
    assert query == {
        "AudioCodecs": "aac",
        "AudioLanguages": "eng",
        "AudioLayouts": "stereo",
        "Containers": "mkv",
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
        "MaxHeight": "2159",
        "MinHeight": "1080",
        "OfficialRatings": "PG-13",
        "ParentId": "library-1",
        "PersonIds": "person-1",
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
    # UserData carries the resume position every card draws its progress bar
    # from, and MediaSourceCount is what marks an item as having versions.
    assert {"UserData", "MediaSourceCount"} <= set(fields.split(","))


def test_every_query_filter_is_classified_as_reachable_or_deliberately_not() -> None:
    """The guard that the eleven-filter regression needed and did not have.

    The old check walked a hand-written list of expected controls, so a filter
    added to CatalogFiltersV2 without a control was invisible to it: absent
    from the schema list, absent from the rail, absent from the failure. This
    walks the schema instead, so the test cannot be quietly outgrown.
    """
    declared = set(CatalogFiltersV2.model_fields)
    classified = set(FILTER_FIELD_TO_CONTROL)

    unclassified = sorted(declared - classified)
    assert not unclassified, (
        "CatalogFiltersV2 accepts filters that FILTER_FIELD_TO_CONTROL does not "
        f"account for: {unclassified}. Give each one a control id, or None with "
        "the reason it is not on the rail."
    )
    stale = sorted(classified - declared)
    assert not stale, f"FILTER_FIELD_TO_CONTROL names filters the schema dropped: {stale}"


def test_filter_options_offer_every_control_the_query_side_accepts(live_watchparty) -> None:
    """The rail is data-driven, so a control absent here is a filter nobody can reach.

    The frontend renders exactly the controls this route returns and drops any
    saved filter whose id is not among them. Emby still honours all of these on
    the query side, so a missing control is a capability the server has and the
    viewer cannot use, which is invisible from the outside.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(
            "/api/v2/items/filter-options",
            params={
                "parent_id": "library-1",
                "include_kinds": "movie",
                "media_kinds": "video",
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
    # The captured catalogues carry many values, so these assert the known one
    # is present and correctly labelled rather than that it is the only row.
    # Pinning a single-element list required the fake to truncate every
    # catalogue to one item, which left a backend that dropped or truncated
    # values indistinguishable from one that did not.
    assert {"value": "Drama", "label": "Drama"} in controls["genre"]["values"]
    assert {"value": "mkv", "label": "MKV"} in controls["container"]["values"]
    assert {"value": "h264", "label": "H264"} in controls["video_codec"]["values"]
    assert {"value": "aac", "label": "AAC"} in controls["audio_codec"]["values"]
    assert {"value": "subrip", "label": "SUBRIP"} in controls["subtitle_codec"]["values"]
    assert "audio_language" not in controls

    # The controls that are not derived from an Emby catalogue. They cost no
    # upstream call, so nothing forces them to be built and they were silently
    # absent for a release: eleven filters the query side accepted and the
    # panel offered no way to set.
    statics = {
        "video_type": [
            {"value": "VideoFile", "label": "VideoFile"},
            {"value": "Bluray", "label": "Bluray"},
            {"value": "Dvd", "label": "Dvd"},
            {"value": "Iso", "label": "Iso"},
        ],
        "resolution": [
            {"value": "any", "label": "Any"},
            {"value": "4K", "label": "4K"},
            {"value": "1080p", "label": "1080p"},
            {"value": "720p", "label": "720p"},
            {"value": "SD", "label": "SD"},
        ],
        "is_3d": [],
        "subtitles": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "trailers": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "extras": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "theme_songs": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "theme_videos": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "locked": [
            {"value": "any", "label": "Any"},
            {"value": "yes", "label": "With"},
            {"value": "no", "label": "Without"},
        ],
        "overview": [
            {"value": "any", "label": "Any"},
            {"value": "with", "label": "With"},
            {"value": "without", "label": "Without"},
        ],
        "missing_provider_ids": [
            {"value": "imdb", "label": "IMDb Id"},
            {"value": "tmdb", "label": "MovieDb Id"},
            {"value": "tvdb", "label": "Tvdb Id"},
        ],
    }
    # Derived from the schema, not from `statics`. A filter added to
    # CatalogFiltersV2 and given a control id here has to actually appear.
    reachable = {control_id for control_id in FILTER_FIELD_TO_CONTROL.values() if control_id}
    missing = sorted(reachable - set(controls))
    assert not missing, f"filter controls the query side accepts but the rail cannot set: {missing}"
    for control_id, values in statics.items():
        assert controls[control_id]["values"] == values, control_id
        assert controls[control_id]["label"], f"{control_id} has nothing to render as its title"

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    catalogue_paths = {
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
    }
    assert catalogue_paths <= {row["path"] for row in recorded}

    # Each catalogue must be scoped to the library being browsed. Asserting
    # only that the endpoint was CALLED passed with every scoping parameter
    # deleted, because the fake ignores the query string: the request would
    # have returned the whole server's genres for one library's filter panel.
    unscoped = []
    for path in sorted(catalogue_paths):
        row = next(row for row in reversed(recorded) if row["path"] == path)
        query = dict(row["query"])
        if query.get("ParentId") != "library-1":
            unscoped.append(f"{path}: ParentId={query.get('ParentId')!r}")
        if query.get("IncludeItemTypes") != "Movie":
            unscoped.append(f"{path}: IncludeItemTypes={query.get('IncludeItemTypes')!r}")
    assert not unscoped, "filter catalogues fetched without the browsed scope:\n" + "\n".join(
        unscoped
    )


def test_no_filter_control_offers_a_value_the_query_schema_rejects(live_watchparty) -> None:
    """The rail and the query contract are written in two places and must agree.

    A control offering a token CatalogFiltersV2 does not list gives the viewer a
    filter that 422s the moment they pick it, and the panel has no way to tell
    them why. 'any' is the rail's own no-op and is never submitted.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/v2/items/filter-options", params={"parent_id": "library-1"})
    finally:
        client.close()

    assert response.status_code == 200
    controls = {control["id"]: control for control in response.json()["controls"]}
    rejected = []
    closed = _closed_vocabularies()
    absent = sorted(control_id for control_id in closed if control_id not in controls)
    assert not absent, (
        f"closed-vocabulary controls the rail never rendered: {absent}. "
        "Skipping them silently is how eleven went missing for a release."
    )
    for control_id, field_name in closed.items():
        control = controls[control_id]
        accepted = _accepted_tokens(field_name)
        rejected.extend(
            f"{control_id}: {value['value']!r} not in {sorted(accepted)}"
            for value in control["values"]
            if value["value"] != "any" and value["value"] not in accepted
        )

    assert not rejected, "filter controls offering values the server rejects:\n" + "\n".join(
        rejected
    )


def test_grouped_search_normalizes_supported_emby_item_types(live_watchparty) -> None:
    live_watchparty.fake.state.search_items = [
        {"Id": "movie-1", "Name": "Matrix", "Type": "Movie"},
        {"Id": "series-1", "Name": "Matrix TV", "Type": "Series"},
        {"Id": "episode-1", "Name": "Matrix Pilot", "Type": "Episode"},
        {"Id": "person-1", "Name": "Matrix Actor", "Type": "Person"},
        {"Id": "box-1", "Name": "Matrix Collection", "Type": "BoxSet"},
    ]
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/v2/items/search/groups", params={"q": "matrix"})
    finally:
        live_watchparty.fake.state.search_items = None
        client.close()

    assert response.status_code == 200
    groups = {group["id"]: group["items"] for group in response.json()["groups"]}
    assert [item["id"] for item in groups["movies"]] == ["movie-1"]
    assert [item["id"] for item in groups["series"]] == ["series-1"]
    assert [item["id"] for item in groups["episodes"]] == ["episode-1"]
    assert [item["id"] for item in groups["people"]] == ["person-1"]
    assert [item["id"] for item in groups["collections"]] == ["box-1"]
    upstream = next(
        row
        for row in live_watchparty.fake.state.requests
        if ("SearchTerm", "matrix") in row["query"]
    )
    assert (
        "IncludeItemTypes",
        "Movie,Series,Episode,Person,BoxSet",
    ) in upstream["query"]


def test_search_asks_for_the_runtime_its_result_cards_display(live_watchparty) -> None:
    """Search hits render into the same grid as a browse page, with a duration.

    The card shows '1h 52m' and, for a part-watched item, 'Played: 1h 2m (41%)
    of 2h 34m'. Both are computed from RunTimeTicks, which Emby only returns
    when Fields asks for it, so dropping it from the search request empties
    those readouts on every search result while browsing looks untouched.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/v2/items/search/groups", params={"q": "matrix"})
    finally:
        client.close()

    assert response.status_code == 200
    search_requests = [
        dict(row["query"])
        for row in live_watchparty.fake.state.requests
        if row["path"].endswith("/Items") and "SearchTerm" in dict(row["query"])
    ]
    assert search_requests, "no upstream search request recorded"
    assert all("RunTimeTicks" in query["Fields"].split(",") for query in search_requests)


def test_grouped_search_fuzzily_matches_spacing_punctuation_and_typos(live_watchparty) -> None:
    """Emby's SearchTerm is punctuation-sensitive; the search box is not.

    'spiderman', 'spider man' and a typo all have to reach 'Spider-Man', which
    Emby answers with nothing for any of the three. The recall comes from a
    second, punctuation-stripped prefix query that is then ranked locally.
    """
    live_watchparty.fake.state.search_responses = {
        "spiderman": [],
        "spider man": [],
        "spidreman": [],
        "spid": [
            {"Id": "movie-1", "Name": "Spider-Man", "Type": "Movie"},
            {"Id": "movie-2", "Name": "Spider-Man 2", "Type": "Movie"},
            {"Id": "near-1", "Name": "Spider Madison", "Type": "Movie"},
            {"Id": "other-1", "Name": "Spider Baby", "Type": "Movie"},
        ],
    }
    client = _unlocked_client(live_watchparty)
    try:
        responses = [
            client.get("/api/v2/items/search/groups", params={"q": query})
            for query in ("spiderman", "spider man", "spidreman")
        ]
    finally:
        live_watchparty.fake.state.search_responses = None
        client.close()

    assert all(response.status_code == 200 for response in responses)
    assert [
        [item["name"] for item in response.json()["groups"][0]["items"]] for response in responses
    ] == [["Spider-Man", "Spider-Man 2"]] * 3
    search_terms = [
        dict(row["query"])["SearchTerm"]
        for row in live_watchparty.fake.state.requests
        if row["path"].endswith("/Items") and "SearchTerm" in dict(row["query"])
    ]
    # The literal term first, then the compacted prefix. The prefix is the
    # whole mechanism: without a second upstream query there are no candidates
    # to rank, however good the local scoring is.
    assert search_terms[-6:] == [
        "spiderman",
        "spid",
        "spider man",
        "spid",
        "spidreman",
        "spid",
    ]


def test_grouped_search_retries_last_name_prefix_for_misspelled_people(live_watchparty) -> None:
    """A misspelled surname leaves the first-name prefix with nothing to rank.

    'sean conery' compacts to a 'sean' prefix, which returns candidates that
    are all poor matches, so the surname gets its own bounded prefix query.
    """
    live_watchparty.fake.state.search_responses = {
        "sean conery": [],
        "sean": [],
        "con": [
            {"Id": "person-1", "Name": "Sean Connery", "Type": "Person"},
            {"Id": "person-2", "Name": "Connor Trinneer", "Type": "Person"},
        ],
    }
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/v2/items/search/groups", params={"q": "sean conery"})
    finally:
        live_watchparty.fake.state.search_responses = None
        client.close()

    assert response.status_code == 200
    groups = {group["id"]: group["items"] for group in response.json()["groups"]}
    assert [item["name"] for item in groups["people"]] == ["Sean Connery"]
    search_terms = [
        dict(row["query"])["SearchTerm"]
        for row in live_watchparty.fake.state.requests
        if row["path"].endswith("/Items") and "SearchTerm" in dict(row["query"])
    ]
    assert search_terms[-3:] == ["sean conery", "sean", "con"]


def test_detail_sections_proxy_artifact_observed_boundaries(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        responses = {
            section: client.get(f"/api/v2/items/movie-1/sections/{section}")
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
        "/api/v2/auth/login", json={"username": "Host", "password": "password"}
    ).raise_for_status()
    guest = httpx.Client(base_url=live_watchparty.url)
    guest.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "guest-client", "display_name": "Guest"},
    ).raise_for_status()
    try:
        assert host.put("/api/v2/items/movie-1/favorite", json={"favorite": True}).json() == {
            "success": True,
            "favorite": True,
        }
        assert host.put("/api/v2/items/movie-1/played", json={"played": False}).json() == {
            "success": True,
            "played": False,
        }
        assert host.get("/api/v2/playlists").json()["items"][0]["id"] == "playlist-1"
        created = host.post("/api/v2/playlists", json={"name": "Party picks"})
        assert created.status_code == 201
        assert created.json() == {"id": "playlist-2", "name": "Party picks"}
        added = host.post("/api/v2/playlists/playlist-2/items", json={"item_id": "movie-1"})
        assert added.json() == {"success": True}
        assert (
            guest.put("/api/v2/items/movie-1/favorite", json={"favorite": True}).status_code == 403
        )
    finally:
        host.close()
        guest.close()

    requests = live_watchparty.fake.state.requests
    assert any(
        row["method"] == "POST" and row["path"].endswith("/FavoriteItems/movie-1")
        for row in requests
    )
    assert any(
        row["method"] == "DELETE" and row["path"].endswith("/PlayedItems/movie-1")
        for row in requests
    )
    assert any(
        row["path"] == "/emby/Playlists"
        and ("Name", "Party picks") in row["query"]
        and ("UserId", "user-1") in row["query"]
        for row in requests
    )
    assert any(
        row["path"] == "/emby/Playlists/playlist-2/Items" and ("Ids", "movie-1") in row["query"]
        for row in requests
    )


def test_series_sections_use_observed_season_and_episode_endpoints(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        seasons = client.get("/api/v2/items/series-1/seasons")
        episodes = client.get("/api/v2/items/series-1/episodes", params={"season_id": "season-1"})
    finally:
        client.close()

    assert seasons.status_code == 200
    assert episodes.status_code == 200
    assert "items" in seasons.json()
    assert "items" in episodes.json()
    requests = live_watchparty.fake.state.requests
    assert any(row["path"] == "/emby/Shows/series-1/Seasons" for row in requests)
    assert any(
        row["path"] == "/emby/Shows/series-1/Episodes" and ("SeasonId", "season-1") in row["query"]
        for row in requests
    )


def test_filtered_prefixes_forward_the_same_filter_contract(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/prefixes",
            json={
                "scope": {"parent_id": "library-1"},
                "sort": {"field": "name", "direction": "ascending"},
                "filters": {"genres": ["Drama"], "playstate": "unplayed"},
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    upstream = live_watchparty.fake.state.requests[-1]
    assert upstream["path"] == "/emby/Items/Prefixes"
    assert ("Genres", "Drama") in upstream["query"]
    assert ("Filters", "IsUnplayed") in upstream["query"]


def test_multi_value_filters_use_the_separator_emby_expects(live_watchparty) -> None:
    """Every list filter was sent with exactly one element.

    A single-element list joins to itself under any separator, so all fourteen
    could be replaced with garbage and the suite stayed green. Emby splits the
    name-like filters on '|' and the id-like ones on ',', and getting that
    wrong silently returns the wrong titles rather than erroring.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/query",
            json={
                "scope": {
                    "parent_id": "library-1",
                    "include_kinds": ["movie"],
                    "media_kinds": ["video"],
                    "recursive": True,
                },
                "page": {"start": 0, "limit": 25},
                "sort": {"field": "name", "direction": "ascending"},
                "filters": {
                    "genres": ["Drama", "Sci-Fi"],
                    "official_ratings": ["PG-13", "R"],
                    "studios": ["Studio A", "Studio B"],
                    "tags": ["Featured", "Classic"],
                    "person_ids": ["person-1", "person-2"],
                    "years": [2023, 2024],
                    "containers": ["mkv", "mp4"],
                    "video_codecs": ["h264", "hevc"],
                    "video_types": ["VideoFile", "Dvd"],
                    "audio_codecs": ["aac", "ac3"],
                    "audio_layouts": ["stereo", "5.1"],
                    "audio_languages": ["eng", "spa"],
                    "subtitle_codecs": ["subrip", "ass"],
                    "subtitle_languages": ["eng", "spa"],
                },
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    query = dict(next(row for row in reversed(recorded) if row["path"].endswith("/Items"))["query"])

    # Pipe-separated: values that may themselves contain a comma.
    assert query["Genres"] == "Drama|Sci-Fi"
    assert query["OfficialRatings"] == "PG-13|R"
    assert query["Studios"] == "Studio A|Studio B"
    assert query["Tags"] == "Featured|Classic"
    # Comma-separated: ids and enumerated tokens.
    assert query["PersonIds"] == "person-1,person-2"
    assert query["Years"] == "2023,2024"
    assert query["Containers"] == "mkv,mp4"
    assert query["VideoCodecs"] == "h264,hevc"
    assert query["VideoTypes"] == "VideoFile,Dvd"
    assert query["AudioCodecs"] == "aac,ac3"
    assert query["AudioLayouts"] == "stereo,5.1"
    assert query["AudioLanguages"] == "eng,spa"
    assert query["SubtitleCodecs"] == "subrip,ass"
    assert query["SubtitleLanguages"] == "eng,spa"
