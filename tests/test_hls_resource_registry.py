from urllib.parse import urljoin

import pytest

from backend.src.hls_registry import HLSResourceRegistry
from backend.src.providers.models import (
    HLSResource,
    PlaybackMethod,
    PlaybackPlan,
    ProviderCredentials,
)
from tests.support.credentials import TEST_HLS_BROWSER_TOKEN, TEST_JELLYFIN_ACCESS_TOKEN


def test_playlist_scanner_preserves_format_and_uses_only_opaque_resource_ids() -> None:
    registry = HLSResourceRegistry()
    plan = PlaybackPlan(
        stream_id="stream-1",
        item_id="movie-1",
        media_source_id="source-1",
        play_session_id="session-1",
        method=PlaybackMethod.HLS_TRANSCODE,
        master=HLSResource("https://media.test/Videos/movie-1/master.m3u8?secret=server"),
        credentials=ProviderCredentials(
            access_token=TEST_JELLYFIN_ACCESS_TOKEN,
            user_id="user-1",
        ),
    )
    registry.install(plan)
    playlist = (
        "#EXTM3U\r\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/TRACK.M3U8?lang=en"\r\n'
        '#EXT-X-MAP:URI="init.mp4?part=1",BYTERANGE="720@0"\r\n'
        '#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"\r\n'
        "variant.M3U8?quality=high\r\n"
        "segment0001.ts?part=1\r\n"
    )

    rewritten = registry.rewrite_playlist(
        plan,
        plan.master,
        playlist,
        resolve=lambda parent, child: HLSResource(urljoin(parent.url, child)),
        app_prefix="/watch",
        token=TEST_HLS_BROWSER_TOKEN,
    )

    assert rewritten.count("\r\n") == playlist.count("\r\n")
    assert "media.test" not in rewritten
    assert TEST_JELLYFIN_ACCESS_TOKEN not in rewritten
    assert "secret=server" not in rewritten
    assert "audio/TRACK.M3U8" not in rewritten
    assert "variant.M3U8" not in rewritten
    assert "segment0001.ts" not in rewritten
    assert rewritten.count("/watch/hls/stream-1/resources/") == 5
    assert rewritten.count(f"?token={TEST_HLS_BROWSER_TOKEN}") == 5
    assert '#EXT-X-MAP:URI="/watch/hls/stream-1/resources/' in rewritten
    assert ',BYTERANGE="720@0"\r\n' in rewritten

    resource_ids = list(plan.resources)
    assert len(resource_ids) == 5
    assert registry.resolve("stream-1", resource_ids[0]) in plan.resources.values()


def test_plan_accepts_only_ten_thousand_unique_resources_but_reuses_duplicates() -> None:
    registry = HLSResourceRegistry()
    plan = PlaybackPlan(
        stream_id="stream-1",
        item_id="movie-1",
        media_source_id="source-1",
        play_session_id="session-1",
        method=PlaybackMethod.HLS_TRANSCODE,
        master=HLSResource("https://media.test/master.m3u8"),
        credentials=ProviderCredentials(
            access_token=TEST_JELLYFIN_ACCESS_TOKEN, user_id="user-1"
        ),
    )
    registry.install(plan)

    def resolve(_parent: HLSResource, child: str) -> HLSResource:
        return HLSResource(f"https://media.test/{child}")

    registry.rewrite_playlist(
        plan,
        plan.master,
        "".join(f"segment-{index}.ts\n" for index in range(10_000)),
        resolve=resolve,
        app_prefix="",
        token=TEST_HLS_BROWSER_TOKEN,
    )
    registry.rewrite_playlist(
        plan,
        plan.master,
        "segment-0.ts\n",
        resolve=resolve,
        app_prefix="",
        token=TEST_HLS_BROWSER_TOKEN,
    )

    assert len(plan.resources) == 10_000
    with pytest.raises(ValueError, match="resource limit"):
        registry.rewrite_playlist(
            plan,
            plan.master,
            "segment-10000.ts\n",
            resolve=resolve,
            app_prefix="",
            token=TEST_HLS_BROWSER_TOKEN,
        )
    assert len(plan.resources) == 10_000
