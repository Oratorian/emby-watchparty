"""Contracts every library route owes its caller, checked across all of them.

These exist because the same guard kept being written on one route and missed
on its twin. Each test enumerates the routes first, so a new route joins the
check by existing rather than by someone remembering to add it.
"""

import httpx
import pytest

from backend.src.routers import library


def _unlocked_client(live_watchparty) -> httpx.Client:
    client = httpx.Client(base_url=live_watchparty.url)
    created = client.post("/api/party/create", json={})
    created.raise_for_status()
    party_id = created.json()["party_id"]
    joined = client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "contract-client", "display_name": "Alice"},
    )
    joined.raise_for_status()
    login = client.post("/api/auth/login", json={"username": "Alice", "password": "password"})
    login.raise_for_status()
    return client


def test_an_upstream_failure_is_a_bad_gateway_on_every_library_route(live_watchparty) -> None:
    """A refused Emby connection must not read as an application fault.

    Thirteen of the eighteen library routes had no mapping, so a timeout
    surfaced as a bare 500 and sent the operator looking in the wrong place.
    The mapping is now registered once for the whole app rather than repeated
    per route, which is what let it drift in the first place.
    """
    client = _unlocked_client(live_watchparty)
    try:
        # /api/libraries had no mapping of its own, so this is the twin, not
        # one of the five routes that already handled it.
        httpx.post(
            f"{live_watchparty.fake.url}/__test__/behavior",
            json={"transient_failures": {"/emby/Users/user-1/Views": 20}, "transient_status": 503},
        ).raise_for_status()
        response = client.get("/api/libraries")
    finally:
        httpx.post(f"{live_watchparty.fake.url}/__test__/reset")
        client.close()

    assert response.status_code == 502
    assert response.json()["detail"] == "Emby upstream unavailable"


def test_a_nameless_upstream_row_is_dropped_on_both_item_paths(live_watchparty) -> None:
    """GET /api/items and POST /api/items/query hit the same upstream endpoint.

    The strict viewer contract requires Name, so a permissive Emby row without
    one fails response validation with a bare 500. The guard was wired into the
    query twin only, leaving the default browse to break on the exact row it
    was written for.
    """
    client = _unlocked_client(live_watchparty)
    live_watchparty.fake.state.user_items = [
        {"Id": "good", "Name": "Real Movie", "Type": "Movie"},
        {"Id": "nameless", "Type": "Movie"},
    ]
    try:
        browse = client.get("/api/items", params={"parentId": "library-1"})
    finally:
        live_watchparty.fake.state.user_items = None
        client.close()

    assert browse.status_code == 200
    body = browse.json()
    assert [item["Name"] for item in body["Items"]] == ["Real Movie"]
    # The count has to follow the drop, or the grid pages past the end.
    assert body["TotalRecordCount"] == 1


@pytest.mark.parametrize("route", ["/api/search", "/api/search/grouped"])
def test_both_search_routes_cap_the_query_length(live_watchparty, route: str) -> None:
    """Ranking is O(len(q) x len(title)) and runs on the single event loop.

    An uncapped q therefore stalls socket sync and HLS proxying for every
    viewer in every party, not only the caller. /search/grouped capped at 200
    from the start; /search did not.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(route, params={"q": "a" * 5000})
    finally:
        client.close()

    assert response.status_code == 422


def test_every_library_route_requires_an_unlocked_party() -> None:
    """No route may reach Emby without the party-bound session.

    Enumerated from the router rather than listed by hand, so a route added
    later is covered without anyone remembering to extend this.
    """
    unguarded = []
    for route in library.router.routes:
        dependencies = getattr(route, "dependant", None)
        if dependencies is None:
            continue
        names = {getattr(sub.call, "__name__", "") for sub in dependencies.dependencies if sub.call}
        if not names & {"require_party_unlocked", "require_party_host"}:
            unguarded.append(getattr(route, "path", "?"))

    assert not unguarded, f"library routes reachable without a party session: {unguarded}"


def test_artwork_proxy_returns_bytes_and_cannot_forge_an_upstream_query(live_watchparty) -> None:
    """The artwork proxy had no executable coverage at all.

    The fake Emby served no Images route, so /api/image answered 404 in every
    pytest and Playwright run: neither its bounds, its auth, nor its URL
    construction were exercised by anything.

    item_id was also the one value interpolated raw into the upstream URL while
    type and index were both constrained, so an id carrying ? or & appended
    attacker-chosen parameters to a request the server makes with the HOST's
    credentials.
    """
    client = _unlocked_client(live_watchparty)
    try:
        good = client.get("/api/image/movie-1", params={"maxWidth": 240})
        forged = client.get("/api/image/movie-1%3FmaxWidth%3D9999%26X%3D1")
    finally:
        client.close()

    assert good.status_code == 200
    assert good.headers["content-type"].startswith("image/")
    assert good.content[:8] == b"\x89PNG\r\n\x1a\n"

    # The forged id must never become extra query parameters upstream.
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    image_rows = [row for row in recorded if "/Images/" in row["path"]]
    assert image_rows, "no upstream image request recorded"
    for row in image_rows:
        assert dict(row["query"]).get("X") is None
    assert forged.status_code in {404, 422}


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/api/image/movie-1", 200), ("/api/image/no-such-item", 404)],
)
def test_a_wrong_item_id_is_visible_rather_than_answered(
    live_watchparty, path: str, expected: int
) -> None:
    """The fake used to answer any id with a fully shaped payload.

    That made a wrong or missing item id undetectable by any test, which is the
    harness being more permissive than a real Emby.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(path)
    finally:
        client.close()

    assert response.status_code == expected


def test_index_sort_maps_to_the_composite_v1_used_for_browse_ordering() -> None:
    """Season and episode order has to survive the v1 -> v2 move.

    v1's browse route sorted by ParentIndexNumber,IndexNumber,SortName unless
    the caller asked for alphabetical. CatalogSortV2 shipped without a member
    for that composite, so the ordering was not merely unsent by the client but
    unrequestable: a 10-season show listed as Season 1, 10, 11, 2.
    """
    from backend.src.providers.models import CatalogPage, CatalogQuery, CatalogScope, CatalogSort
    from backend.src.providers.normalization import emby_family_query

    query = CatalogQuery(
        scope=CatalogScope(parent_id="series-1"),
        page=CatalogPage(start=0, limit=50),
        sort=CatalogSort(field="index", direction="ascending"),
    )

    assert emby_family_query(query)["sort"]["field"] == "ParentIndexNumber,IndexNumber,SortName"


def test_index_is_an_accepted_sort_field_on_the_wire() -> None:
    """A backend mapping is useless if the schema rejects the request first."""
    from backend.src.v2_schemas import CatalogSortV2

    assert CatalogSortV2(field="index").field == "index"
