"""Async HTTP transport for media-server providers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, ClassVar

import httpx

if TYPE_CHECKING:
    import logging

QueryScalar = str | int | float | bool | None
QueryParams = (
    Mapping[str, QueryScalar | Sequence[QueryScalar]]
    | list[tuple[str, QueryScalar]]
    | tuple[tuple[str, QueryScalar], ...]
    | str
    | bytes
)


class MediaServerGateway:
    RETRYABLE_STATUSES: ClassVar[frozenset[int]] = frozenset({502, 503, 504})
    RETRY_DELAYS = (0.1, 0.25)
    SAFE_METHODS: ClassVar[frozenset[str]] = frozenset({"GET", "HEAD"})

    def __init__(self, client: httpx.AsyncClient, server_url: str, logger: logging.Logger):
        self.client = client
        self.server_url = server_url.rstrip("/")
        self.logger = logger

    def url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.server_url}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        headers: dict[str, str] | None = None,
        params: QueryParams | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        method = method.upper()
        attempts = 1 + (len(self.RETRY_DELAYS) if method in self.SAFE_METHODS else 0)
        for attempt in range(attempts):
            try:
                response = await self.client.request(
                    method,
                    self.url(path),
                    # httpx treats an explicit `timeout=None` as "no timeout
                    # at all", not "use the client's default", so passing
                    # this straight through actively overrode the client's
                    # Timeout(30.0, connect=5.0, pool=5.0) and left every
                    # caller that omitted a timeout completely unbounded. A
                    # slow or wedged Emby could then pin a worker slot until
                    # the OS gave up on the socket. USE_CLIENT_DEFAULT is
                    # httpx's sentinel for "fall back to the client", which
                    # is what `None` was always meant to mean here.
                    timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else timeout,
                    headers=headers,
                    params=params,
                    json=json,
                )
            except (httpx.ConnectError, httpx.ReadTimeout):
                if attempt + 1 >= attempts:
                    raise
                self.logger.warning(
                    "Emby request retry: method=%s attempt=%s reason=transport",
                    method,
                    attempt + 1,
                )
                await asyncio.sleep(self.RETRY_DELAYS[attempt])
                continue

            if response.status_code not in self.RETRYABLE_STATUSES or attempt + 1 >= attempts:
                return response
            await response.aclose()
            self.logger.warning(
                "Emby request retry: method=%s attempt=%s status=%s",
                method,
                attempt + 1,
                response.status_code,
            )
            await asyncio.sleep(self.RETRY_DELAYS[attempt])
        raise RuntimeError("unreachable retry state")

    async def get(
        self,
        path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        headers: dict[str, str] | None = None,
        params: QueryParams | None = None,
    ) -> httpx.Response:
        return await self.request("GET", path, timeout=timeout, headers=headers, params=params)

    async def post(
        self,
        path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        headers: dict[str, str] | None = None,
        params: QueryParams | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST", path, timeout=timeout, headers=headers, params=params, json=json
        )

    async def delete(
        self,
        path: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        headers: dict[str, str] | None = None,
        params: QueryParams | None = None,
    ) -> httpx.Response:
        return await self.request("DELETE", path, timeout=timeout, headers=headers, params=params)

    async def open_stream(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: QueryParams | None = None,
    ) -> httpx.Response:
        request = self.client.build_request(
            "GET",
            self.url(path),
            headers=headers,
            params=params,
        )
        return await self.client.send(request, stream=True)


# Backward-compatible import for existing Emby-focused callers and tests.
EmbyGateway = MediaServerGateway
