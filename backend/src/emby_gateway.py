"""Async HTTP boundary for Emby with one timeout and retry policy."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class EmbyGateway:
    RETRYABLE_STATUSES = {502, 503, 504}
    RETRY_DELAYS = (0.1, 0.25)
    SAFE_METHODS = {"GET", "HEAD"}

    def __init__(self, client: httpx.AsyncClient, server_url: str, logger):
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
        **kwargs: Any,
    ) -> httpx.Response:
        method = method.upper()
        attempts = 1 + (len(self.RETRY_DELAYS) if method in self.SAFE_METHODS else 0)
        for attempt in range(attempts):
            try:
                response = await self.client.request(
                    method,
                    self.url(path),
                    timeout=timeout,
                    **kwargs,
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

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)

    async def open_stream(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: Any = None,
    ) -> httpx.Response:
        request = self.client.build_request(
            "GET",
            self.url(path),
            headers=headers,
            params=params,
        )
        return await self.client.send(request, stream=True)
