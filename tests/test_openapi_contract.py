"""What /docs and /redoc promise must match what the routes actually return.

These are enumerated from the routers rather than listed by hand, so a route
added later is covered by existing rather than by someone remembering to add
it here. That matters more than usual for this file: the published schema is
the only description of the API most callers will ever read, and a wrong one
is worse than none because it is trusted.
"""

from fastapi.routing import APIRoute

from backend.src.routers import admin, auth, avatar, health, library, media, party, quality

ROUTERS = (admin, auth, avatar, health, library, media, party, quality)
EMBY_DEPENDENCIES = {"get_emby_client", "get_emby_gateway"}
# Routes that reach Emby but convert an upstream failure themselves, so a 502
# can never escape them and declaring one would be its own kind of wrong.
#
# Every one of these goes through EmbyClient.authenticate, which is the single
# method that translates httpx errors into EmbyUnavailableError; the routes
# then answer with their own domain result. Everywhere else the httpx error
# propagates to the application-level handler and becomes a 502.
#
# Deliberately an explicit exception list rather than a heuristic: a route
# added later is assumed to need the 502 until someone states otherwise here,
# which is the direction that fails safe.
SELF_HANDLED_UPSTREAM = {
    ("admin", "/api/admin/login"),
    ("auth", "/api/auth/login"),
    ("avatar", "/api/avatar/host/{party_id}"),
    ("health", "/api/ready"),
    ("party", "/api/party/create"),
    ("party", "/api/party/{party_id}/join"),
}
# Guard name -> the status codes it can produce, which the route must declare.
GUARD_CODES = {
    "require_party_session": {401, 404},
    "require_party_unlocked": {401, 404, 423},
    "require_host_token": {401, 404, 423},
    "require_party_host": {401, 403, 404, 423},
    "require_admin": {401, 403, 404},
}


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            names.add(getattr(sub.call, "__name__", ""))
        names |= _dependency_names(sub)
    return names


def _routes():
    for module in ROUTERS:
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                name = module.__name__.rsplit(".", 1)[-1]
                yield name, route, _dependency_names(route.dependant)


def _declared(route: APIRoute) -> set[int]:
    """Status codes the published schema lists, router defaults included."""
    codes = {int(code) for code in route.responses}
    router_level = getattr(route, "responses", None)
    del router_level
    return codes


def test_every_emby_backed_route_documents_the_upstream_failure() -> None:
    """An Emby transport failure becomes a 502 through one app-level handler.

    Because that handler is central rather than per route, nothing forces a
    route to mention it, and 23 of the 27 Emby-backed routes did not. /docs and
    /redoc therefore described an error contract the server does not honour.
    """
    undocumented = [
        f"{module}: {sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
        for module, route, names in _routes()
        if names & EMBY_DEPENDENCIES
        and (module, route.path) not in SELF_HANDLED_UPSTREAM
        and 502 not in _declared(route)
    ]

    assert not undocumented, "Emby-backed routes that do not document 502:\n" + "\n".join(
        sorted(undocumented)
    )


def test_no_route_documents_an_upstream_failure_it_cannot_produce() -> None:
    """The reverse direction, so the fix cannot be "declare 502 everywhere".

    A schema that over-promises is wrong in a quieter way than one that
    under-promises: a caller writes handling for a status the server will never
    send, and never finds out.
    """
    overdocumented = [
        f"{module}: {sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
        for module, route, names in _routes()
        if 502 in _declared(route)
        and (not names & EMBY_DEPENDENCIES or (module, route.path) in SELF_HANDLED_UPSTREAM)
    ]

    assert not overdocumented, "routes documenting a 502 they cannot return:\n" + "\n".join(
        sorted(overdocumented)
    )


def test_every_guarded_route_documents_the_codes_its_guard_returns() -> None:
    """Seven routes added with the library work declared no responses at all.

    They are host-gated and party-gated, so they can answer 401, 403, 404 and
    423, and the published schema showed only 200 and 422. A caller reading it
    would treat an authorization failure as an unexpected error.
    """
    gaps = []
    for module, route, names in _routes():
        expected: set[int] = set()
        for guard, codes in GUARD_CODES.items():
            if guard in names:
                expected |= codes
        if not expected:
            continue
        missing = expected - _declared(route)
        if missing:
            method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
            gaps.append(f"{module}: {method} {route.path} missing {sorted(missing)}")

    assert not gaps, "guarded routes whose schema hides their failure modes:\n" + "\n".join(
        sorted(gaps)
    )
