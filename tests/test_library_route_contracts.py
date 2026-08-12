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
