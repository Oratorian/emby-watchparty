import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.dependencies import (
    get_config,
    get_emby_client,
    get_emby_gateway,
    get_logger,
    get_party_manager,
    get_token_manager,
)
from backend.src.routers import hls


class _Config:
    EMBY_SERVER_URL = "http://emby.test"
    APP_PREFIX = ""
    ENABLE_HLS_TOKEN_VALIDATION = True


class _EmbyClient:
    def _headers(self, access_token, user_id):
        return {}


class _TokenManager:
    def get_party_id(self, token):
        return "PARTY" if token == "party-token" else None

    def validate(self, token, **_kwargs):
        return token == "party-token"


class _PartyManager:
    def exists(self, party_id):
        return party_id == "PARTY"

    def get(self, party_id):
        if party_id != "PARTY":
            return None
        return {
            "host_access_token": "host-token",
            "host_user_id": "host-user",
            "users": {},
        }


class _Logger:
    def debug(self, _message):
        pass

    def error(self, _message):
        pass

    def warning(self, _message):
        pass


class _HTTPClient:
    def __init__(self, response):
        self.response = response

    async def get(self, *_args, **_kwargs):
        self.params = _kwargs.get("params")
        return self.response

    def build_request(self, method, url, **kwargs):
        return httpx.Request(method, url, headers=kwargs.get("headers"), params=kwargs.get("params"))

    async def send(self, _request, stream=False):
        return self.response

    async def open_stream(self, *_args, **_kwargs):
        self.params = _kwargs.get("params")
        return self.response

def _client(upstream_response):
    app = FastAPI()
    app.include_router(hls.router)
    app.dependency_overrides.update(
        {
            get_config: lambda: _Config(),
            get_emby_client: lambda: _EmbyClient(),
            get_token_manager: lambda: _TokenManager(),
            get_party_manager: lambda: _PartyManager(),
            get_logger: lambda: _Logger(),
            get_emby_gateway: lambda: _HTTPClient(upstream_response),
        }
    )
    return TestClient(app)


class HLSProxyTests(unittest.TestCase):
    def test_approved_duplicate_query_parameters_are_preserved(self):
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )
        app = FastAPI()
        gateway = _HTTPClient(upstream_response)
        app.include_router(hls.router)
        app.dependency_overrides.update({
            get_config: lambda: _Config(),
            get_emby_client: lambda: _EmbyClient(),
            get_token_manager: lambda: _TokenManager(),
            get_party_manager: lambda: _PartyManager(),
            get_logger: lambda: _Logger(),
            get_emby_gateway: lambda: gateway,
        })

        response = TestClient(app).get(
            "/hls/123/master.m3u8?AudioCodec=aac&AudioCodec=mp3&token=party-token"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(gateway.params, [("AudioCodec", "aac"), ("AudioCodec", "mp3")])

    def test_playlist_rejects_foreign_absolute_uri_before_token_injection(self):
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\nhttps://evil.example/segment.ts\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

        response = _client(upstream_response).get(
            "/hls/123/master.m3u8?token=party-token"
        )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("party-token", response.text)

    def test_segment_proxy_rejects_encoded_path_traversal(self):
        upstream_response = httpx.Response(
            200,
            content=b"must-not-be-returned",
            request=httpx.Request("GET", "http://emby.test/admin"),
        )

        response = _client(upstream_response).get(
            "/hls/123/%2E%2E%2Fadmin?token=party-token"
        )

        self.assertEqual(response.status_code, 400)

    def test_master_playlist_returns_usable_tokenized_variant_url(self):
        upstream_playlist = (
            "#EXTM3U\r\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2000000\r\n"
            "main.m3u8?MediaSourceId=source&PlaySessionId=session\r\n"
        )
        upstream_response = httpx.Response(
            200,
            text=upstream_playlist,
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client(upstream_response).get(
                "/hls/123/master.m3u8"
                "?MediaSourceId=source&PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.text.splitlines(),
            [
                "#EXTM3U",
                "#EXT-X-STREAM-INF:BANDWIDTH=2000000",
                "main.m3u8?MediaSourceId=source&PlaySessionId=session&token=party-token",
            ],
        )

    def test_variant_playlist_returns_usable_tokenized_segment_url(self):
        upstream_playlist = (
            "#EXTM3U\r\n"
            "#EXTINF:6.000,\r\n"
            "hls1/main0.ts?PlaySessionId=session\r\n"
        )
        upstream_response = httpx.Response(
            200,
            text=upstream_playlist,
            request=httpx.Request("GET", "http://emby.test/main.m3u8"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client(upstream_response).get(
                "/hls/123/main.m3u8?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.text.splitlines(),
            [
                "#EXTM3U",
                "#EXTINF:6.000,",
                "hls1/main0.ts?PlaySessionId=session&token=party-token",
            ],
        )

    def test_playlist_rewrite_preserves_crlf_and_final_line_ending(self):
        upstream_playlist = "#EXTM3U\r\nmain.m3u8?PlaySessionId=session\r\n"
        upstream_response = httpx.Response(
            200,
            content=upstream_playlist.encode("utf-8"),
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client(upstream_response).get(
                "/hls/123/master.m3u8?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(
            response.content,
            (
                "#EXTM3U\r\n"
                "main.m3u8?PlaySessionId=session&token=party-token\r\n"
            ).encode("utf-8"),
        )

    def test_segment_proxy_returns_playable_transport_stream_bytes(self):
        upstream_response = httpx.Response(
            200,
            content=b"transport-stream-bytes",
            request=httpx.Request("GET", "http://emby.test/hls1/main0.ts"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client(upstream_response).get(
                "/hls/123/hls1/main0.ts?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].lower(), "video/mp2t")
        self.assertEqual(response.content, b"transport-stream-bytes")

    def test_segment_proxy_streams_without_buffered_content_length(self):
        upstream_response = httpx.Response(
            200,
            content=b"streamed-transport-bytes",
            request=httpx.Request("GET", "http://emby.test/hls1/main0.ts"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client(upstream_response).get(
                "/hls/123/hls1/main0.ts?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"streamed-transport-bytes")
        self.assertNotIn("content-length", response.headers)
