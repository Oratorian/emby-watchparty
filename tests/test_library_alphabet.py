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
        "/api/auth/login",
        json={"username": "AlphabetLibrary", "password": "password"},
    )
    login.raise_for_status()
    assert login.json()["success"] is True
    return client


def test_library_prefixes_follow_the_browsed_collection_scope(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get("/api/items/prefixes", params={"parentId": "library-1"})
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {"Prefixes": ["#", "A", "M", "Z"]}

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    prefix_request = next(row for row in recorded if row["path"] == "/emby/Items/Prefixes")
    query = dict(prefix_request["query"])
    assert query["UserId"] == "user-alphabet"
    assert query["ParentId"] == "library-1"
    assert query["Recursive"] == "true"
    assert query["IncludeItemTypes"] == "Movie"


def test_letter_jump_returns_an_absolute_page_in_alphabetical_order(live_watchparty) -> None:
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(
            "/api/items",
            params={
                "parentId": "library-1",
                "limit": 50,
                "sortMode": "alphabetical",
                "anchorPrefix": "M",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert body["StartIndex"] == 100
    assert body["Items"][0]["Name"] == "Middle Movie 0000"

    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    item_requests = [
        dict(row["query"]) for row in recorded if row["path"] == "/emby/Users/user-alphabet/Items"
    ]
    count_query = next(query for query in item_requests if "NameLessThan" in query)
    page_query = next(query for query in item_requests if query.get("StartIndex") == "100")

    assert count_query["NameLessThan"] == "M"
    assert count_query["Limit"] == "1"
    assert count_query["SortBy"] == "SortName"
    assert page_query["SortBy"] == "SortName"
    assert "SortName" in page_query["Fields"].split(",")


def _scope_of(recorded, path_suffix: str) -> dict:
    rows = [dict(row["query"]) for row in recorded if row["path"].endswith(path_suffix)]
    assert rows, f"no upstream request to {path_suffix}"
    return rows[-1]


def test_filtered_and_unfiltered_browsing_resolve_the_same_scope(live_watchparty) -> None:
    """The two paths must agree about what a library contains.

    GET /api/items resolves item types from the collection type server-side.
    POST /api/items/query used to take them from a second map maintained in the
    frontend, and the two disagreed: the query path sent MediaTypes=Video for a
    tvshows library, but a real Emby Series carries no MediaType at all, so the
    grid went empty the moment a user applied any filter or changed the sort.
    """
    client = _unlocked_client(live_watchparty)
    try:
        browse = client.get("/api/items", params={"parentId": "library-2"})
        assert browse.status_code == 200
        recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
        browse_query = _scope_of(recorded, "/Items")

        queried = client.post(
            "/api/items/query",
            json={
                "scope": {
                    "parent_id": "library-2",
                    "include_item_types": [],
                    "media_types": [],
                    "recursive": False,
                },
                "page": {"start_index": 0, "limit": 50},
                "sort": {"field": "SortName", "direction": "Ascending"},
                "filters": {"favorite": True},
            },
        )
        assert queried.status_code == 200
        recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
        query_scope = _scope_of(recorded, "/Items")
    finally:
        client.close()

    assert browse_query["IncludeItemTypes"] == "Series"
    assert query_scope["IncludeItemTypes"] == browse_query["IncludeItemTypes"]
    assert query_scope["Recursive"] == browse_query["Recursive"] == "true"
    # A Series has no MediaType, so sending one matches zero rows upstream.
    assert "MediaTypes" not in query_scope
