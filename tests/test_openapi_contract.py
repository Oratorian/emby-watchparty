"""What /docs and /redoc promise must match what the routes actually return.

These are enumerated from the mounted route surface rather than listed by
hand, so a route added later is covered by existing rather than by someone
remembering to add it here. That matters more than usual for this file: the
published schema is the only description of the API most callers will ever
read, and a wrong one is worse than none because it is trusted.

Enumerating API_ROUTERS rather than a tuple of modules is deliberate: the
tuple could fall out of step with what the application mounts, and then this
file would be checking a surface nobody serves.
"""

from fastapi.routing import APIRoute

from backend.src.routers import API_ROUTERS

# Anything that can reach the media server can meet a transport failure.
UPSTREAM_DEPENDENCIES = {"get_emby_client", "get_emby_gateway", "get_media_server"}
# Routes that reach the media server but convert an upstream failure
# themselves, so a 502 can never escape them and declaring one would be its own
# kind of wrong.
#
# The authentication routes go through the provider's authenticate/verify path,
# which translates transport errors into a domain answer the caller can act on
# ("server unavailable; check MEDIA_SERVER_URL"). /api/v2/media-server and
# /api/v2/auth/status only read the configured provider's identity and never
# leave the process. The intro route swallows every provider failure and
# degrades to "no intro here", which is what keeps a degraded media server from
# turning each playback start into a 500.
#
# Deliberately an explicit exception list rather than a heuristic: a route
# added later is assumed to need the 502 until someone states otherwise here,
# which is the direction that fails safe.
SELF_HANDLED_UPSTREAM = {
    "/api/admin/login",
    "/api/avatar/host/{party_id}",
    "/api/ready",
    "/api/party/create",
    "/api/party/{party_id}/join",
    "/api/v2/media-server",
    "/api/v2/auth/login",
    "/api/v2/auth/status",
    "/api/v2/items/{item_id}/intro",
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
    for router in API_ROUTERS:
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield route, _dependency_names(route.dependant)


def _label(route: APIRoute) -> str:
    return f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"


def _declared(route: APIRoute) -> set[int]:
    """Status codes the published schema lists, router defaults included."""
    return {int(code) for code in route.responses}


def test_every_media_server_backed_route_documents_the_upstream_failure() -> None:
    """A transport failure becomes a 502 through one app-level handler.

    Because that handler is central rather than per route, nothing forces a
    route to mention it. The v1 library router declared it once for all
    eighteen of its routes; v2 declares it per route, which is exactly the
    arrangement that let it drift the first time.
    """
    undocumented = [
        _label(route)
        for route, names in _routes()
        if names & UPSTREAM_DEPENDENCIES
        and route.path not in SELF_HANDLED_UPSTREAM
        and 502 not in _declared(route)
    ]

    assert not undocumented, "media-server-backed routes that do not document 502:\n" + "\n".join(
        sorted(undocumented)
    )


def test_no_route_documents_an_upstream_failure_it_cannot_produce() -> None:
    """The reverse direction, so the fix cannot be "declare 502 everywhere".

    A schema that over-promises is wrong in a quieter way than one that
    under-promises: a caller writes handling for a status the server will never
    send, and never finds out.
    """
    overdocumented = [
        _label(route)
        for route, names in _routes()
        if 502 in _declared(route)
        and (not names & UPSTREAM_DEPENDENCIES or route.path in SELF_HANDLED_UPSTREAM)
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
    for route, names in _routes():
        expected: set[int] = set()
        for guard, codes in GUARD_CODES.items():
            if guard in names:
                expected |= codes
        if not expected:
            continue
        missing = expected - _declared(route)
        if missing:
            gaps.append(f"{_label(route)} missing {sorted(missing)}")

    assert not gaps, "guarded routes whose schema hides their failure modes:\n" + "\n".join(
        sorted(gaps)
    )


def test_every_documented_response_says_what_it_is() -> None:
    """A response row with no description renders as an empty cell in /docs.

    The routes that hand back raw bytes are the ones that need the sentence
    most: their schema is a media type and nothing else, so without a
    description the reader is told a 200 returns image/jpeg and never what the
    image is of.
    """
    undescribed = [
        f"{_label(route)} -> {code}"
        for route, _ in _routes()
        for code, body in route.responses.items()
        if not str(body.get("description") or "").strip()
    ]

    assert not undescribed, "documented responses with an empty description:\n" + "\n".join(
        sorted(undescribed)
    )
