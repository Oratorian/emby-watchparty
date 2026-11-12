"""Bounded per-viewer show previews, separate from synchronized party playback."""

from __future__ import annotations

import asyncio
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.src.hls_registry import HLSResourceRegistry
from backend.src.providers.models import (
    CatalogPage,
    CatalogQuery,
    CatalogScope,
    CatalogSort,
    PlaybackRequest,
    ProviderCredentials,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    import httpx

    from backend.src.party_manager import PartyManager
    from backend.src.providers.base import MediaServerProvider
    from backend.src.providers.models import PlaybackPlan

PREVIEW_SECONDS = 120.0
PREVIEW_TTL_SECONDS = 180
MAX_PREVIEWS = 16
MAX_PREVIEW_REQUESTS = 8


class PreviewUnavailableError(Exception):
    """A show cannot currently provide a background preview."""


class PreviewCapacityError(Exception):
    """All bounded preview slots are in use."""


@dataclass(eq=False, repr=False)
class ShowPreview:
    preview_id: str
    party_id: str
    client_id: str
    credentials: ProviderCredentials
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    start_seconds: float = 0.0
    expires_at: float = 0.0
    plan: PlaybackPlan | None = None
    cancelled: bool = False
    prepare_task: asyncio.Task | None = None
    expiry_task: asyncio.Task | None = None
    cleanup_task: asyncio.Task | None = None
    requests: set[asyncio.Task] = field(default_factory=set)
    responses: set[httpx.Response] = field(default_factory=set)


class PreviewManager:
    """Own one temporary preview per viewer, including cancellation and expiry."""

    def __init__(
        self,
        provider: MediaServerProvider,
        parties: PartyManager,
        logger: logging.Logger,
        *,
        ttl: float = PREVIEW_TTL_SECONDS,
        capacity: int = MAX_PREVIEWS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = HLSResourceRegistry()
        self._provider = provider
        self._parties = parties
        self._logger = logger
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._records: dict[str, ShowPreview] = {}
        self._owners: dict[tuple[str, str], ShowPreview] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    def _host_matches(self, preview: ShowPreview) -> bool:
        party = self._parties.get(preview.party_id)
        return bool(
            party
            and self._parties.is_unlocked(preview.party_id)
            and not party.playback_state.playing
            and preview.client_id in party.sid_client_ids.values()
            and party.host_access_token == preview.credentials.access_token
            and party.host_user_id == preview.credentials.user_id
        )

    async def create(self, party_id: str, client_id: str, series_id: str) -> ShowPreview:
        owner = (party_id, client_id)
        while True:
            async with self._lock:
                previous = self._owners.get(owner)
                if previous is None:
                    if self._closed:
                        raise PreviewUnavailableError
                    if len(self._records) >= self._capacity:
                        raise PreviewCapacityError
                    party = self._parties.get(party_id)
                    if (
                        not party
                        or not self._parties.is_unlocked(party_id)
                        or party.playback_state.playing
                        or client_id not in party.sid_client_ids.values()
                    ):
                        raise PreviewUnavailableError
                    preview = ShowPreview(
                        preview_id=secrets.token_urlsafe(24),
                        party_id=party_id,
                        client_id=client_id,
                        credentials=ProviderCredentials(
                            party.host_access_token or "", party.host_user_id or ""
                        ),
                    )
                    self._records[preview.preview_id] = preview
                    self._owners[owner] = preview
                    preview.prepare_task = asyncio.create_task(self._prepare(preview, series_id))
                    break
            await self._discard(previous)
        try:
            await preview.prepare_task
            return preview
        except BaseException:
            await self._discard(preview)
            raise

    async def _prepare(self, preview: ShowPreview, series_id: str) -> None:
        async with asyncio.timeout(20):
            details = await self._provider.get_details(series_id, preview.credentials)
            if details is None or details.kind != "series":
                raise PreviewUnavailableError
            # The providers already support random sorting. Fetch only a small
            # candidate page, rather than every episode of a long-running show.
            page = await self._provider.query_catalog(
                CatalogQuery(
                    scope=CatalogScope(
                        parent_id=series_id, include_kinds=("episode",), recursive=True
                    ),
                    page=CatalogPage(limit=8),
                    sort=CatalogSort(field="random"),
                ),
                preview.credentials,
            )
            candidates = [
                item
                for item in page.items
                if item.kind == "episode"
                and item.is_playable
                and item.runtime_seconds is not None
                and math.isfinite(item.runtime_seconds)
                and item.runtime_seconds >= PREVIEW_SECONDS + 15
                and item.series_id in {None, series_id}
            ]
            if not candidates:
                raise PreviewUnavailableError
            episode = secrets.choice(candidates)
            runtime = episode.runtime_seconds or 0.0
            first = min(120.0, max(10.0, runtime * 0.15))
            last = min(runtime - PREVIEW_SECONDS - 5, runtime * 0.75)
            first = min(first, last)
            preview.start_seconds = (
                first + secrets.randbelow(max(1, int((last - first) * 1000))) / 1000
            )
            # Real transcoding gives the preview a predictable independent HLS
            # timeline, including source files with unusually wide keyframes.
            preview.plan = await self._provider.prepare_playback(
                PlaybackRequest(
                    item_id=episode.id,
                    credentials=preview.credentials,
                    subtitle_index=-1,
                    quality="360p-750",
                    start_seconds=preview.start_seconds,
                    client_codecs=frozenset({"h264"}),
                    force_transcode=True,
                )
            )
        async with self._lock:
            if (
                preview.cancelled
                or self._owners.get((preview.party_id, preview.client_id)) is not preview
                or not self._host_matches(preview)
                or self._closed
            ):
                raise PreviewUnavailableError
            self._records.pop(preview.preview_id, None)
            preview.preview_id = preview.plan.stream_id
            self._records[preview.preview_id] = preview
            self.registry.install(preview.plan)
            preview.expires_at = self._clock() + self._ttl
            preview.expiry_task = asyncio.create_task(self._expire(preview))

    async def _expire(self, preview: ShowPreview) -> None:
        while not preview.cancelled:
            remaining = preview.expires_at - self._clock()
            if remaining <= 0 or not self._host_matches(preview):
                await self._discard(preview)
                return
            await asyncio.sleep(min(remaining, 1.0))

    async def authorize(
        self, preview_id: str, party_id: str, client_id: str, token: str
    ) -> ShowPreview | None:
        preview = self._records.get(preview_id)
        if (
            preview is None
            or preview.cancelled
            or preview.plan is None
            or preview.party_id != party_id
            or preview.client_id != client_id
            or not secrets.compare_digest(preview.token, token)
        ):
            return None
        if preview.expires_at <= self._clock() or not self._host_matches(preview):
            await self._discard(preview)
            return None
        return preview

    async def stop(self, preview_id: str, party_id: str, client_id: str) -> bool:
        preview = self._records.get(preview_id)
        if preview is None or preview.party_id != party_id or preview.client_id != client_id:
            return False
        await self._discard(preview)
        return True

    def _active(self, preview: ShowPreview) -> bool:
        return bool(
            not preview.cancelled
            and self._records.get(preview.preview_id) is preview
            and self._owners.get((preview.party_id, preview.client_id)) is preview
            and self.registry.get_plan(preview.preview_id) is preview.plan
            and preview.expires_at > self._clock()
            and self._host_matches(preview)
        )

    async def close_response(self, preview: ShowPreview, response: httpx.Response) -> None:
        try:
            if not response.is_closed:
                await response.aclose()
        finally:
            preview.responses.discard(response)

    async def run_request(
        self,
        preview: ShowPreview,
        request_factory: Callable[[], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        """Own upstream work until revocation can safely stop its encoding."""

        async def execute() -> httpx.Response:
            response = None
            try:
                response = await request_factory()
                async with self._lock:
                    if not self._active(preview):
                        raise PreviewUnavailableError
                    preview.responses.add(response)
                return response
            except BaseException:
                if response is not None:
                    await self.close_response(preview, response)
                raise

        async with self._lock:
            if not self._active(preview) or len(preview.requests) >= MAX_PREVIEW_REQUESTS:
                raise PreviewUnavailableError
            task = asyncio.create_task(execute())
            preview.requests.add(task)
        try:
            response = await task
            current = asyncio.current_task()
            cancelled = bool(current and current.cancelling())
            if cancelled or not self._active(preview):
                await self.close_response(preview, response)
                if cancelled:
                    raise asyncio.CancelledError
                raise PreviewUnavailableError
            return response
        except asyncio.CancelledError:
            if preview.cancelled:
                raise PreviewUnavailableError from None
            await self._discard(preview)
            raise
        finally:
            preview.requests.discard(task)

    async def _discard(self, preview: ShowPreview) -> None:
        async with self._lock:
            if preview.cleanup_task is None:
                preview.cancelled = True
                owner = (preview.party_id, preview.client_id)
                if self._owners.get(owner) is preview:
                    self._owners.pop(owner)
                if preview.plan:
                    self.registry.revoke(preview.plan.stream_id)
                current = asyncio.current_task()
                for task in (preview.prepare_task, preview.expiry_task, *preview.requests):
                    if task and task is not current and not task.done():
                        task.cancel()
                preview.cleanup_task = asyncio.create_task(self._cleanup(preview))
            cleanup_task = preview.cleanup_task
        await asyncio.shield(cleanup_task)

    async def _cleanup(self, preview: ShowPreview) -> None:
        try:
            if preview.prepare_task and not preview.prepare_task.done():
                await asyncio.gather(preview.prepare_task, return_exceptions=True)
            # A cancelled fetch may suppress cancellation and finish late.
            # Wait for all such requests, close every returned response, and
            # only then send the final stop to the media server.
            if preview.requests:
                await asyncio.gather(*preview.requests, return_exceptions=True)
            if preview.responses:
                await asyncio.gather(
                    *(
                        self.close_response(preview, response)
                        for response in list(preview.responses)
                    ),
                    return_exceptions=True,
                )
            if preview.plan:
                try:
                    async with asyncio.timeout(5):
                        await self._provider.cancel_preview(preview.plan)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("Preview cleanup failed: error=%s", type(exc).__name__)
        finally:
            if preview.plan:
                self.registry.revoke(preview.plan.stream_id)
            self._records.pop(preview.preview_id, None)

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(self._discard(preview) for preview in list(self._records.values())))
