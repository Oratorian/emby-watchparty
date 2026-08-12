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
