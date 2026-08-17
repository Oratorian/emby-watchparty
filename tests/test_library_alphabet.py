import httpx


def _unlocked_client(live_watchparty) -> httpx.Client:
    client = httpx.Client(base_url=live_watchparty.url)
    created = client.post("/api/party/create", json={})
    created.raise_for_status()
    party_id = created.json()["party_id"]
    joined = client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "alphabet-client", "display_name": "Alice"},
    )
    joined.raise_for_status()
    login = client.post(
        "/api/v2/auth/login",
        json={"username": "AlphabetLibrary", "password": "password"},
    )
    login.raise_for_status()
    assert login.json()["success"] is True
    return client


def test_library_prefixes_follow_the_browsed_collection_scope(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/prefixes",
            json={"scope": {"parent_id": "library-1"}},
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {"prefixes": ["#", "A", "M", "Z"]}

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    prefix_request = next(row for row in recorded if row["path"] == "/emby/Items/Prefixes")
    query = dict(prefix_request["query"])
    assert query["UserId"] == "user-alphabet"
    assert query["ParentId"] == "library-1"
    assert query["Recursive"] == "true"
    assert query["IncludeItemTypes"] == "Movie"


def test_letter_jump_returns_an_absolute_page_in_alphabetical_order(live_watchparty) -> None:
    """A letter is a position in the whole library, not a filter on one page.

    The rail has to answer with the page the letter actually starts on, which
    means counting everything that sorts before it upstream and using that as
    the offset. Filtering a page client-side instead silently drops every title
    under that letter beyond the first page.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/query",
            json={
                "scope": {"parent_id": "library-1"},
                "page": {"start": 0, "limit": 50},
                "sort": {"field": "name", "direction": "ascending"},
                "anchor_prefix": "M",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == 100
    assert body["items"][0]["name"] == "Middle Movie 0000"

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    item_requests = [
        dict(row["query"]) for row in recorded if row["path"] == "/emby/Users/user-alphabet/Items"
    ]
    count_query = next(query for query in item_requests if "NameLessThan" in query)
    page_query = next(query for query in item_requests if query.get("StartIndex") == "100")

    assert count_query["NameLessThan"] == "M"
    # One row, for the count alone. Without the cap the offset probe pulls a
    # full page of items nothing reads.
    assert count_query["Limit"] == "1"
    assert count_query["SortBy"] == "SortName"
    assert page_query["SortBy"] == "SortName"


def _scope_of(recorded, path: str) -> dict:
    rows = [dict(row["query"]) for row in recorded if row["path"] == path]
    assert rows, f"no upstream request to {path}"
    return rows[-1]


def test_the_grid_and_the_alphabet_rail_resolve_the_same_scope(live_watchparty) -> None:
    """The two must agree about what a library contains.

    Item types are resolved from the collection type server-side. They used to
    come from a second map maintained in the frontend, and the two disagreed:
    the query path sent MediaTypes=Video for a tvshows library, but a real Emby
    Series carries no MediaType at all, so the grid went empty the moment a
    user applied any filter or changed the sort. The rail runs the same
    resolution, and a rail scoped differently from the grid enables letters the
    grid cannot fill.
    """
    client = _unlocked_client(live_watchparty)
    try:
        grid = client.post(
            "/api/v2/items/query",
            json={
                "scope": {"parent_id": "library-2"},
                "page": {"start": 0, "limit": 50},
                "sort": {"field": "name", "direction": "ascending"},
                "filters": {"favorite": True},
            },
        )
        assert grid.status_code == 200
        rail = client.post(
            "/api/v2/items/prefixes",
            json={"scope": {"parent_id": "library-2"}, "filters": {"favorite": True}},
        )
        assert rail.status_code == 200
    finally:
        client.close()

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    grid_scope = _scope_of(recorded, "/emby/Users/user-alphabet/Items")
    rail_scope = _scope_of(recorded, "/emby/Items/Prefixes")

    assert grid_scope["IncludeItemTypes"] == "Series"
    assert rail_scope["IncludeItemTypes"] == grid_scope["IncludeItemTypes"]
    assert rail_scope["Recursive"] == grid_scope["Recursive"] == "true"
    # A Series has no MediaType, so sending one matches zero rows upstream.
    assert "MediaTypes" not in grid_scope
    assert "MediaTypes" not in rail_scope


def test_filtered_prefixes_carry_the_user_its_filters_need(live_watchparty) -> None:
    """Emby cannot evaluate per-user Filters without a user.

    This route forwards IsPlayed/IsUnplayed/IsResumable/IsFavorite, all of
    which are user state, so omitting the user made the alphabet rail enable
    letters the grid did not contain.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.post(
            "/api/v2/items/prefixes",
            json={
                "scope": {"parent_id": "library-1"},
                "page": {"start": 0, "limit": 50},
                "sort": {"field": "name", "direction": "ascending"},
                "filters": {"playstate": "unplayed", "favorite": True},
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    query = dict(
        next(row for row in reversed(recorded) if row["path"] == "/emby/Items/Prefixes")["query"]
    )
    assert query["UserId"] == "user-alphabet"
    assert query["Filters"] == "IsUnplayed"
