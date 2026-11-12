"""Emby's opaque HLS resources stay inside their authenticated item plan."""

import asyncio
import logging
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from backend.src.emby_client import EmbyClient
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers.emby import EmbyProvider
from backend.src.providers.models import (
    HLSResource,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackRequest,
    ProviderCredentials,
    UnsafeProviderResourceError,
)
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN

SERVER_URL = "http://emby.test/base"
ITEM_ROOT = f"{SERVER_URL}/emby/Videos/episode-1/"


def _provider(client: httpx.AsyncClient, server_url: str = SERVER_URL) -> EmbyProvider:
    logger = logging.getLogger("test")
    gateway = MediaServerGateway(client, server_url, logger)
    emby = EmbyClient(server_url, "test-api-key", logger, gateway)
    return EmbyProvider(emby, SimpleNamespace(APP_PREFIX="", FORCE_TRANSCODE=False))


def _plan(server_url: str = SERVER_URL) -> PlaybackPlan:
    return PlaybackPlan(
        stream_id="preview-stream-1",
        item_id="episode-1",
        media_source_id="source-1",
        play_session_id="play-session-1",
        method=PlaybackMethod.HLS_TRANSCODE,
        master=HLSResource(f"{server_url}/emby/Videos/episode-1/master.m3u8"),
        credentials=ProviderCredentials(TEST_JELLYFIN_ACCESS_TOKEN, "user-1"),
        upstream_headers={"X-Source-Requirement": "required"},
    )


def test_emby_resolves_registered_nested_resources_within_the_requested_item() -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient() as client:
            provider = _provider(client)
            plan = _plan()
            variant = provider.resolve_hls_resource(plan, plan.master, "hls/main/index.m3u8?part=1")
            assert variant.url == f"{ITEM_ROOT}hls/main/index.m3u8?part=1"
            plan.resources["variant"] = variant
            segment = provider.resolve_hls_resource(plan, variant, "0.ts")
            assert segment.url == f"{ITEM_ROOT}hls/main/0.ts"
            root_relative = provider.resolve_hls_resource(
                plan, plan.master, "/base/emby/Videos/episode-1/hls/main/0.ts"
            )
            assert root_relative == segment

    asyncio.run(exercise())


@pytest.mark.parametrize("server_url", ["http://emby.test", SERVER_URL])
@pytest.mark.parametrize("route", ["emby/videos", "EmBy/ViDeOs"])
def test_emby_accepts_fixed_route_case_variation_without_changing_item_scope(
    server_url: str, route: str
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"segment")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider(client, server_url)
            plan = _plan(server_url)
            path = f"{urlsplit(server_url).path}/{route}/episode-1/segment.ts"
            resource = provider.resolve_hls_resource(plan, plan.master, path)
            plan.resources["segment"] = resource
            assert (await provider.fetch_hls_resource(plan, resource)).content == b"segment"
            assert requests[0].url.path == path

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "https://foreign.test/segment.ts",
        "//foreign.test/segment.ts",
        "http://emby.test:81/base/emby/Videos/episode-1/segment.ts",
        "https://emby.test/base/emby/Videos/episode-1/segment.ts",
        "/base/emby/Videos/other-item/segment.ts",
        "/base/emby/videos/episode-10/segment.ts",
        "/base/emby/videos/Episode-1/segment.ts",
        "/BASE/emby/videos/episode-1/segment.ts",
        "/base2/emby/videos/episode-1/segment.ts",
        "/emby/Videos/episode-1/segment.ts",
        "nested/../segment.ts",
        "nested/%2e%2e/segment.ts",
        "nested/%252e%252e/segment.ts",
        "nested%2f..%2fsegment.ts",
        "nested\\..\\segment.ts",
        "nested%5c..%5csegment.ts",
        "segment.ts#fragment",
        "segment.ts%23fragment",
        "segment.ts\r\n",
        "segment.ts%00",
        "http://[malformed/segment.ts",
    ],
)
def test_emby_rejects_unapproved_playlist_uris(uri: str) -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient() as client:
            provider = _provider(client)
            plan = _plan()
            with pytest.raises(UnsafeProviderResourceError):
                provider.resolve_hls_resource(plan, plan.master, uri)

    asyncio.run(exercise())


def test_emby_rejects_an_unregistered_parent_before_resolving_children() -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeProviderResourceError, match="not registered"):
                _provider(client).resolve_hls_resource(
                    _plan(), HLSResource(f"{ITEM_ROOT}unknown.m3u8"), "segment.ts"
                )

    asyncio.run(exercise())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("registered", [False, True])
def test_emby_validates_the_final_resource_before_sending_credentials(
    streaming: bool, registered: bool
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider(client)
            plan = _plan()
            foreign = HLSResource("http://foreign.test/segment.ts")
            if registered:
                plan.resources["foreign"] = foreign
            fetch = provider.open_hls_resource if streaming else provider.fetch_hls_resource
            with pytest.raises(UnsafeProviderResourceError):
                await fetch(plan, foreign)
            plan.master = foreign
            with pytest.raises(UnsafeProviderResourceError):
                await provider.fetch_hls_resource(plan, foreign)
            assert requests == []

    asyncio.run(exercise())


def test_emby_fetch_preserves_plan_auth_required_headers_range_and_head() -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"" if request.method == "HEAD" else b"#EXTM3U\n")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider(client)
            plan = _plan()
            response = await provider.fetch_hls_resource(plan, plan.master)
            assert response.content == b"#EXTM3U\n"
            response = await provider.fetch_hls_resource(
                plan, plan.master, range_header="bytes=0-4", head=True
            )
            assert response.content == b""

    asyncio.run(exercise())
    assert [request.method for request in requests] == ["GET", "HEAD"]
    assert requests[1].headers["range"] == "bytes=0-4"
    for request in requests:
        assert request.headers["x-emby-token"] == TEST_JELLYFIN_ACCESS_TOKEN
        assert request.headers["x-source-requirement"] == "required"
        assert request.extensions["timeout"]["read"] == 30.0


@pytest.mark.parametrize("streaming", [False, True])
def test_emby_never_follows_resource_redirects_even_if_the_client_normally_does(
    streaming: bool,
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://foreign.test/steal"})

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(upstream), follow_redirects=True
        ) as client:
            provider = _provider(client)
            plan = _plan()
            response = (
                await provider.open_hls_resource(plan, plan.master)
                if streaming
                else await provider.fetch_hls_resource(plan, plan.master)
            )
            assert response.status_code == 302
            await response.aclose()
            assert len(requests) == 1

    asyncio.run(exercise())


def test_emby_segment_stream_is_not_buffered_and_can_be_closed_after_partial_read() -> None:
    class SegmentStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"first-"
            yield b"second"

        async def aclose(self) -> None:
            self.closed = True

    stream = SegmentStream()
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(206, headers={"Content-Range": "bytes 0-11/12"}, stream=stream)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider(client)
            plan = _plan()
            segment = HLSResource(f"{ITEM_ROOT}segment.ts")
            plan.resources["segment"] = segment
            response = await provider.open_hls_resource(plan, segment, range_header="bytes=0-11")
            assert response.status_code == 206
            assert response.is_stream_consumed is False
            assert stream.closed is False
            assert await anext(response.aiter_bytes()) == b"first-"
            await response.aclose()
            assert stream.closed is True

    asyncio.run(exercise())
    assert requests[0].headers["range"] == "bytes=0-11"
    assert requests[0].headers["x-emby-token"] == TEST_JELLYFIN_ACCESS_TOKEN
    assert requests[0].headers["x-source-requirement"] == "required"


def test_emby_retains_required_source_headers_in_a_prepared_plan() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "PlaySessionId": "session-1",
                "MediaSources": [
                    {
                        "Id": "source-1",
                        "MediaStreams": [{"Type": "Video", "Codec": "h264"}],
                        "RequiredHttpHeaders": {"X-Source-Requirement": "required"},
                    }
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            plan = await _provider(client).prepare_playback(
                PlaybackRequest(item_id="episode-1", credentials=_plan().credentials)
            )
            assert plan.upstream_headers == {"X-Source-Requirement": "required"}

    asyncio.run(exercise())
