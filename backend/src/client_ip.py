"""Trust-aware client IP resolution for security controls."""

from collections.abc import Iterable, Mapping
from ipaddress import ip_address, ip_network
from typing import Any

from fastapi import Request


def resolve_client_ip(
    peer_ip: str, x_forwarded_for: str, trusted_proxy_cidrs: Iterable[str]
) -> str:
    """Return caller IP without trusting headers from an untrusted peer."""
    try:
        peer = ip_address(peer_ip)
        networks = tuple(ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs)
    except ValueError:
        return peer_ip

    if not networks or not any(peer in network for network in networks):
        return peer_ip

    forwarded: list[str] = []
    for raw in x_forwarded_for.split(","):
        candidate = raw.strip()
        try:
            ip_address(candidate)
        except ValueError:
            continue
        forwarded.append(candidate)

    if not forwarded:
        return peer_ip

    for candidate in reversed(forwarded):
        parsed = ip_address(candidate)
        if not any(parsed in network for network in networks):
            return candidate
    return peer_ip


def request_client_ip(request: Request, trusted_proxy_cidrs: Iterable[str]) -> str:
    peer_ip = request.client.host if request.client else "0.0.0.0"
    return resolve_client_ip(
        peer_ip=peer_ip,
        x_forwarded_for=request.headers.get("x-forwarded-for", ""),
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )


def environ_client_ip(environ: Mapping[str, Any], trusted_proxy_cidrs: Iterable[str]) -> str:
    """Resolve the caller IP from a Socket.IO handshake environ.

    The socket counterpart to `request_client_ip`. `REMOTE_ADDR` cannot
    be used here: every python-engineio async driver writes the literal
    string "127.0.0.1" into the environ rather than the connection's
    address (see `engineio/async_drivers/asgi.py`, and the aiohttp,
    sanic and tornado drivers alongside it). Reading it therefore hands
    `resolve_client_ip` the same constant for every connection, which
    collapses every caller onto one rate-limit bucket and, because
    loopback is not in `TRUSTED_PROXY_CIDRS` by default, also discards
    the forwarded chain even when an operator has configured it
    correctly.

    The real peer is only reachable through the ASGI scope. Uvicorn runs
    with `proxy_headers=False`, so `scope["client"]` is the true TCP
    peer and has not been rewritten from a header; deciding whether to
    trust `X-Forwarded-For` stays with `resolve_client_ip`.
    """
    scope = environ.get("asgi.scope")
    client = scope.get("client") if isinstance(scope, Mapping) else None
    return resolve_client_ip(
        peer_ip=str(client[0]) if client else "0.0.0.0",
        x_forwarded_for=str(environ.get("HTTP_X_FORWARDED_FOR", "")),
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )
