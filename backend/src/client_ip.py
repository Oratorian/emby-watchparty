"""Trust-aware client IP resolution for security controls."""

from collections.abc import Iterable
from ipaddress import ip_address, ip_network

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
