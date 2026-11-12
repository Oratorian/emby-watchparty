"""Preview negotiation and cancellation stay separate from watched playback."""

import asyncio
import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers import create_provider
from backend.src.providers.models import (
    HLSResource,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackRequest,
    ProviderCredentials,
)
from backend.src.stream_builder import StreamBuilder
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN


def _config(provider_type: str) -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_URL=f"http://{provider_type}.test",
            MEDIA_SERVER_API_KEY=f"{provider_type}-key",
            APP_ENV="development",
            SESSION_SECRET="",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            MEDIA_SERVER_TYPE=provider_type,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def _provider(provider_type: str, client: httpx.AsyncClient):
    config = _config(provider_type)
    gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))
    return create_provider(config, logging.getLogger("test"), gateway)


def _plan(play_session_id: str = "preview-session-1") -> PlaybackPlan:
    return PlaybackPlan(
        stream_id="preview-stream-1",
        item_id="episode-1",
        media_source_id="source-1",
        play_session_id=play_session_id,
        method=PlaybackMethod.HLS_TRANSCODE,
        master=HLSResource("http://media.test/Videos/episode-1/master.m3u8"),
        credentials=ProviderCredentials(TEST_JELLYFIN_ACCESS_TOKEN, "user-1"),
    )


@pytest.mark.parametrize("provider_type", ["emby", "jellyfin"])
def test_preview_cancellation_only_stops_the_matching_encoding(provider_type: str) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider(provider_type, client)
            assert await provider.cancel_preview(_plan()) is True
            assert len(requests) == 1
            request = requests[0]
            assert request.method == "DELETE"
            assert request.url.path == (
                "/emby/Videos/ActiveEncodings"
                if provider_type == "emby"
                else "/Videos/ActiveEncodings"
            )
            assert request.url.params["PlaySessionId"] == "preview-session-1"
            assert request.url.params["DeviceId"] == provider.device_id
            assert request.url.params["api_key"] == TEST_JELLYFIN_ACCESS_TOKEN
            # The sole request is encoding cancellation, never a playback
            # check-in that could advance the host's watched position.
            assert "/Sessions/" not in request.url.path

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_type", ["emby", "jellyfin"])
@pytest.mark.parametrize("session_id", ["", " \t"])
def test_preview_cancellation_never_broadly_stops_a_device(
    provider_type: str, session_id: str
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            with pytest.raises(ValueError, match="play session ID"):
                await _provider(provider_type, client).cancel_preview(_plan(session_id))
            assert requests == []

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_type", ["emby", "jellyfin"])
def test_preview_cancellation_reports_upstream_failure_without_a_stop_checkin(
    provider_type: str,
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            assert await _provider(provider_type, client).cancel_preview(_plan()) is False
            assert len(requests) == 1
            assert requests[0].method == "DELETE"

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_type", ["emby", "jellyfin"])
def test_preview_negotiation_caps_dimensions_bitrate_and_disables_stream_copy(
    provider_type: str,
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "PlaySessionId": "preview-session-1",
                "MediaSources": [
                    {
                        "Id": "source-1",
                        "TranscodingSubProtocol": "hls",
                        "TranscodingReasons": ["ContainerBitrateExceedsLimit"],
                        "TranscodingUrl": (
                            "/Videos/episode-1/master.m3u8?PlaySessionId=preview-session-1"
                        ),
                        "MediaStreams": [
                            {"Type": "Video", "Codec": "h264", "Width": 1920, "BitRate": 4_000_000}
                        ],
                    }
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            plan = await _provider(provider_type, client).prepare_playback(
                PlaybackRequest(
                    item_id="episode-1",
                    credentials=_plan().credentials,
                    quality="360p-750",
                    start_seconds=240,
                    force_transcode=True,
                )
            )
            assert plan.method is PlaybackMethod.HLS_TRANSCODE
            assert len(requests) == 1
            if provider_type == "emby":
                assert requests[0].url.params["MaxStreamingBitrate"] == "750000"
                params = parse_qs(urlsplit(plan.master.url).query)
                assert params["MaxWidth"] == ["640"]
                assert params["MaxHeight"] == ["360"]
                assert params["VideoBitrate"] == ["750000"]
                assert params["VideoCodec"] == ["h264"]
                assert params["EnableAutoStreamCopy"] == ["false"]
                assert params["StartTimeTicks"] == ["2400000000"]
            else:
                body = json.loads(requests[0].content)
                assert body["MaxStreamingBitrate"] == 750000
                assert body["AllowVideoStreamCopy"] is False
                assert body["StartTimeTicks"] == 2_400_000_000
                profile = body["DeviceProfile"]
                conditions = profile["CodecProfiles"][0]["Conditions"]
                assert {row["Property"]: row["Value"] for row in conditions} == {
                    "Width": "640",
                    "Height": "360",
                }
                assert profile["TranscodingProfiles"][0]["VideoCodec"] == "h264"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("configured", "requested"), [(False, False), (False, True), (True, False)]
)
def test_per_preview_transcoding_preserves_the_global_transcode_setting(
    configured: bool, requested: bool
) -> None:
    builder = StreamBuilder(
        SimpleNamespace(device_id="test-device"),
        logging.getLogger("test"),
        SimpleNamespace(FORCE_TRANSCODE=configured),
    )
    params = builder.build_params(
        {"MediaStreams": [{"Type": "Video", "Codec": "h264"}]},
        "source-1",
        "session-1",
        None,
        None,
        "auto",
        force_transcode=requested,
    )
    assert ("EnableAutoStreamCopy=false" in params) is (configured or requested)


def test_emby_marks_a_forced_auto_plan_as_transcoding() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "PlaySessionId": "preview-session-1",
                "MediaSources": [
                    {"Id": "source-1", "MediaStreams": [{"Type": "Video", "Codec": "h264"}]}
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            provider = _provider("emby", client)
            request = PlaybackRequest(item_id="episode-1", credentials=_plan().credentials)
            assert (await provider.prepare_playback(request)).method is PlaybackMethod.HLS_COPY
            forced = PlaybackRequest(
                item_id="episode-1", credentials=_plan().credentials, force_transcode=True
            )
            assert (await provider.prepare_playback(forced)).method is PlaybackMethod.HLS_TRANSCODE

    asyncio.run(exercise())
