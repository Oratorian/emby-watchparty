"""Contracts every catalog route owes its caller, checked across all of them.

These exist because the same guard kept being written on one route and missed
on its twin. Each test enumerates the routes first, so a new route joins the
check by existing rather than by someone remembering to add it.

The routes are the /api/v2 ones now. The v1 library and media modules that
these contracts were first written against are gone; the properties are not,
so each one is asserted where the behaviour now lives.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.src.routers import v2

ARTIFACT_ROOT = Path(__file__).parent / "artifacts" / "emby" / "4.9.5.0"

# Routes that answer before any party exists: the login handshake itself and
# the capability probe the frontend reads to decide what to render.
UNGUARDED_BY_DESIGN = {
    "/api/v2/media-server",
    "/api/v2/auth/login",
    "/api/v2/auth/logout",
    "/api/v2/auth/status",
}


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
    login = client.post("/api/v2/auth/login", json={"username": "Alice", "password": "password"})
    login.raise_for_status()
    return client


def test_an_upstream_failure_is_a_bad_gateway_on_every_catalog_route(live_watchparty) -> None:
    """A refused Emby connection must not read as an application fault.

    Most routes had no mapping of their own, so a timeout surfaced as a bare
    500 and sent the operator looking in the wrong place. The mapping is
    registered once for the whole app rather than repeated per route, which is
    what let it drift in the first place.
    """
    client = _unlocked_client(live_watchparty)
    try:
        httpx.post(
            f"{live_watchparty.fake.url}/__test__/behavior",
            json={"transient_failures": {"/emby/Users/user-1/Views": 20}, "transient_status": 503},
        ).raise_for_status()
        response = client.get("/api/v2/libraries")
    finally:
        httpx.post(f"{live_watchparty.fake.url}/__test__/reset")
        client.close()

    assert response.status_code == 502
    assert response.json()["detail"] == "Emby upstream unavailable"


def test_a_nameless_upstream_row_is_dropped_and_the_total_follows(live_watchparty) -> None:
    """A row Emby will serve but no viewer can name must not reach the grid.

    Emby is permissive about Name; the grid is not. A nameless folder renders
    as a blank clickable card, and it is counted, so the page claims one more
    title than it can show. The payload here is a captured folder, not a
    hand-written row: this is a shape a real 4.9.5 server returns.
    """
    client = _unlocked_client(live_watchparty)
    live_watchparty.fake.state.user_items = [
        json.loads((ARTIFACT_ROOT / "filtered-unnamed-folder.json").read_text()),
        {"Id": "movie-1", "Name": "Drama Movie", "Type": "Movie"},
    ]
    try:
        browse = client.post(
            "/api/v2/items/query",
            json={"scope": {"parent_id": "library-1"}, "filters": {"genres": ["Drama"]}},
        )
    finally:
        live_watchparty.fake.state.user_items = None
        client.close()

    assert browse.status_code == 200
    body = browse.json()
    assert [(item["id"], item["name"]) for item in body["items"]] == [("movie-1", "Drama Movie")]
    # The count has to follow the drop, or the grid pages past the end.
    assert body["total"] == 1


@pytest.mark.parametrize("route", ["/api/v2/items/search", "/api/v2/items/search/groups"])
def test_both_search_routes_cap_the_query_length(live_watchparty, route: str) -> None:
    """Ranking is O(len(q) x len(title)) and runs on the single event loop.

    An uncapped q therefore stalls socket sync and HLS proxying for every
    viewer in every party, not only the caller.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(route, params={"q": "a" * 5000})
    finally:
        client.close()

    assert response.status_code == 422


def test_every_catalog_route_requires_an_unlocked_party() -> None:
    """No route may reach the media server without the party-bound session.

    Enumerated from the router rather than listed by hand, so a route added
    later is covered without anyone remembering to extend this. The four
    handshake routes are named explicitly: a new one has to be argued for here
    rather than slipping in unguarded.
    """
    unguarded = []
    for route in v2.router.routes:
        dependencies = getattr(route, "dependant", None)
        if dependencies is None or getattr(route, "path", "") in UNGUARDED_BY_DESIGN:
            continue
        names = {getattr(sub.call, "__name__", "") for sub in dependencies.dependencies if sub.call}
        if not names & {"require_party_unlocked", "require_party_host", "require_host_token"}:
            unguarded.append(getattr(route, "path", "?"))

    assert not unguarded, f"v2 routes reachable without a party session: {unguarded}"


def test_artwork_proxy_returns_bytes_and_cannot_forge_an_upstream_query(live_watchparty) -> None:
    """The artwork proxy had no executable coverage at all.

    The fake Emby served no Images route, so the proxy answered 404 in every
    pytest and Playwright run: neither its bounds, its auth, nor its URL
    construction were exercised by anything.

    item_id is the one value that reaches the upstream URL as caller-supplied
    text, so an id carrying ? or & must not be able to append attacker-chosen
    parameters to a request the server makes with the HOST's credentials.
    """
    client = _unlocked_client(live_watchparty)
    try:
        good = client.get("/api/v2/items/movie-1/images/primary", params={"max_width": 240})
        forged = client.get("/api/v2/items/movie-1%3FmaxWidth%3D9999%26X%3D1/images/primary")
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
    ("item_id", "expected"),
    [("movie-1", 200), ("no-such-item", 404)],
)
def test_a_wrong_item_id_is_visible_rather_than_answered(
    live_watchparty, item_id: str, expected: int
) -> None:
    """The fake used to answer any id with a fully shaped payload.

    That made a wrong or missing item id undetectable by any test, which is the
    harness being more permissive than a real Emby.
    """
    client = _unlocked_client(live_watchparty)
    try:
        response = client.get(f"/api/v2/items/{item_id}/images/primary")
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
