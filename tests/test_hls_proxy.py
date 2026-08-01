import unittest

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


# The sid the HLS token was minted for. The real HLSTokenManager stores
# this alongside the token and hands it to user_in_party_fn, so the party
# dict below has to list it as a member for validation to pass.
_TOKEN_SID = "sid-1"

_DEVICE_ID = "emby-watchparty-test"


class _Config:
    EMBY_SERVER_URL = "http://emby.test"
    APP_PREFIX = ""
    ENABLE_HLS_TOKEN_VALIDATION = True


class _EmbyClient:
    """Mirrors EmbyClient._headers, which is what hls.py signs Emby calls with.

    Returning the real header shape (rather than {}) is what lets the tests
    assert the host token actually reaches Emby.
    """

    def _headers(self, access_token=None, user_id=None):
        if access_token:
            auth_value = (
                f'Emby UserId="{user_id or ""}", Client="WatchParty", '
                f'Device="Web", DeviceId="{_DEVICE_ID}", Version="1.0", '
                f'Token="{access_token}"'
            )
            return {
                "X-Emby-Token": access_token,
                "Content-Type": "application/json",
                "X-Emby-Authorization": auth_value,
            }
        return {"X-Emby-Token": "admin-api-key", "Content-Type": "application/json"}


class _TokenManager:
    """Mirrors HLSTokenManager for the two members hls.py calls.

    validate() keeps the real required parameters and actually invokes both
    callables; collapsing them into **kwargs would leave the router's own
    party-membership lambda (hls.py) completely unexercised.
    """

    _TOKENS = {"party-token": {"party_id": "PARTY", "sid": _TOKEN_SID}}

    def get_party_id(self, token):
        data = self._TOKENS.get(token)
        return data["party_id"] if data else None

    def validate(self, token, party_exists_fn, user_in_party_fn):
        data = self._TOKENS.get(token)
        if not data:
            return False
        return party_exists_fn(data["party_id"]) and user_in_party_fn(
            data["party_id"], data["sid"]
        )


class _PartyManager:
    def __init__(self, users=None):
        self._users = {_TOKEN_SID: "alice"} if users is None else users

    def exists(self, party_id):
        return party_id == "PARTY"

    def get(self, party_id):
        if party_id != "PARTY":
            return None
        return {
            "host_access_token": "host-token",
            "host_user_id": "host-user",
            "users": self._users,
        }


class _Logger:
    def debug(self, msg, *args, **kwargs):
        pass

    def error(self, msg, *args, **kwargs):
        pass

    def warning(self, _message):
        pass


class _HTTPClient:
    def __init__(self, response):
        self.response = response
        self.kwargs = {}

    async def get(self, *_args, **_kwargs):
        self.kwargs = _kwargs
        self.params = _kwargs.get("params")
        return self.response

    def build_request(self, method, url, **kwargs):
        return httpx.Request(
            method,
            url,
            headers=kwargs.get("headers"),
            params=kwargs.get("params"),
        )

    async def send(self, _request, stream=False):
        return self.response

    async def open_stream(self, *_args, **_kwargs):
        self.kwargs = _kwargs
        self.params = _kwargs.get("params")
        return self.response


def _client(upstream_response, party_manager=None):
    app = FastAPI()
    app.include_router(hls.router)
    party_manager = party_manager or _PartyManager()
    gateway = _HTTPClient(upstream_response)
    app.state.fake_emby_gateway = gateway
    app.dependency_overrides.update(
        {
            get_config: lambda: _Config(),
            get_emby_client: lambda: _EmbyClient(),
            get_token_manager: lambda: _TokenManager(),
            get_party_manager: lambda: party_manager,
            get_logger: lambda: _Logger(),
            get_emby_gateway: lambda: gateway,
        }
    )
    return TestClient(app)


def _assert_upstream_auth(gateway):
    """The host token must reach Emby on every proxied request."""
    headers = gateway.kwargs["headers"]
    assert headers["X-Emby-Token"] == "host-token", headers
    assert 'Token="host-token"' in headers["X-Emby-Authorization"], headers
    assert 'UserId="host-user"' in headers["X-Emby-Authorization"], headers


def _assert_upstream_timeout(gateway):
    """Every upstream Emby call must be time-bounded, see _EMBY_HTTP_TIMEOUT."""
    assert gateway.kwargs.get("timeout") == hls._EMBY_HTTP_TIMEOUT, gateway.kwargs


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

        client = _client(upstream_response)
        response = client.get(
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
        _assert_upstream_auth(client.app.state.fake_emby_gateway)
        _assert_upstream_timeout(client.app.state.fake_emby_gateway)

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

        client = _client(upstream_response)
        response = client.get(
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
        _assert_upstream_auth(client.app.state.fake_emby_gateway)
        _assert_upstream_timeout(client.app.state.fake_emby_gateway)

    def test_playlist_rewrite_preserves_crlf_and_final_line_ending(self):
        upstream_playlist = "#EXTM3U\r\nmain.m3u8?PlaySessionId=session\r\n"
        upstream_response = httpx.Response(
            200,
            content=upstream_playlist.encode("utf-8"),
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

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

        client = _client(upstream_response)
        response = client.get(
            "/hls/123/hls1/main0.ts?PlaySessionId=session&token=party-token"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].lower(), "video/mp2t")
        self.assertEqual(response.content, b"transport-stream-bytes")
        _assert_upstream_auth(client.app.state.fake_emby_gateway)

    def test_segment_proxy_streams_without_buffered_content_length(self):
        upstream_response = httpx.Response(
            200,
            content=b"streamed-transport-bytes",
            request=httpx.Request("GET", "http://emby.test/hls1/main0.ts"),
        )

        response = _client(upstream_response).get(
            "/hls/123/hls1/main0.ts?PlaySessionId=session&token=party-token"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"streamed-transport-bytes")
        self.assertNotIn("content-length", response.headers)
    def test_token_for_user_no_longer_in_party_is_rejected(self):
        """The membership check is the only authorization these routes have.

        A token that is otherwise valid, known and unexpired, must stop
        working once its sid is no longer a member of the party.
        """
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\r\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )
        evicted = _PartyManager(users={})

        client = _client(upstream_response, party_manager=evicted)
        response = client.get(
            "/hls/123/master.m3u8?PlaySessionId=session&token=party-token"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.app.state.fake_emby_gateway.kwargs, {})
