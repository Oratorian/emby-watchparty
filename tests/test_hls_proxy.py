import base64
import json
import unittest
from unittest.mock import patch

import httpx
import itsdangerous
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.src.dependencies import (
    get_config,
    get_emby_client,
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

# The routes are gated by require_host_token, which reads request.session,
# so the test app needs SessionMiddleware exactly as backend/app.py wires
# it. SessionMiddleware signs its cookies, so the fixture has to mint a
# properly signed one rather than a raw JSON blob.
_SESSION_SECRET = "test-session-secret"
_SESSION_COOKIE = "ewp_session"


def _session_cookie(party_id="PARTY", client_id="client-1", display_name="alice"):
    """Mint a cookie SessionMiddleware will accept.

    Keys match what POST /api/party/{id}/join writes and what
    require_party_session reads back.
    """
    payload = {
        "party_id": party_id,
        "client_id": client_id,
        "display_name": display_name,
    }
    data = base64.b64encode(json.dumps(payload).encode("utf-8"))
    signer = itsdangerous.TimestampSigner(_SESSION_SECRET)
    return signer.sign(data).decode("utf-8")


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
    """Mirrors the PartyManager surface hls.py and require_host_token use.

    `is_unlocked` is deliberately absent: require_host_token never calls
    it. That is the PLAYING-ONLY distinction, a host who has left still
    keeps the in-flight video alive.
    """

    def __init__(self, users=None, host_access_token="host-token", known=("PARTY",)):
        self._users = {_TOKEN_SID: "alice"} if users is None else users
        self._host_access_token = host_access_token
        self._known = set(known)

    def exists(self, party_id):
        return party_id in self._known

    def get(self, party_id):
        if party_id not in self._known:
            return None
        return {
            "host_access_token": self._host_access_token,
            "host_user_id": "host-user",
            "users": self._users,
        }

    def has_host_token(self, party_id):
        party = self.get(party_id)
        return bool(party and party.get("host_access_token"))


class _Logger:
    def debug(self, msg, *args, **kwargs):
        pass

    def error(self, msg, *args, **kwargs):
        pass


def _client(party_manager=None, session=True, session_party_id="PARTY"):
    app = FastAPI()
    app.include_router(hls.router)
    app.add_middleware(
        SessionMiddleware,
        secret_key=_SESSION_SECRET,
        session_cookie=_SESSION_COOKIE,
        same_site="lax",
        https_only=False,
    )
    party_manager = party_manager or _PartyManager()
    # Override only the service getters. Overriding require_party_session
    # would delete the very gate under test, since FastAPI applies
    # overrides to sub-dependencies too.
    app.dependency_overrides.update(
        {
            get_config: lambda: _Config(),
            get_emby_client: lambda: _EmbyClient(),
            get_token_manager: lambda: _TokenManager(),
            get_party_manager: lambda: party_manager,
            get_logger: lambda: _Logger(),
        }
    )
    client = TestClient(app)
    if session:
        client.cookies.set(_SESSION_COOKIE, _session_cookie(party_id=session_party_id))
    return client


def _assert_upstream_auth(mock_get):
    """The host token must reach Emby on every proxied request."""
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["X-Emby-Token"] == "host-token", headers
    assert 'Token="host-token"' in headers["X-Emby-Authorization"], headers
    assert 'UserId="host-user"' in headers["X-Emby-Authorization"], headers


def _assert_upstream_timeout(mock_get):
    """Every upstream Emby call must be time-bounded, see _EMBY_HTTP_TIMEOUT."""
    assert mock_get.call_args.kwargs.get("timeout") == hls._EMBY_HTTP_TIMEOUT, (
        mock_get.call_args.kwargs
    )


class HLSProxyTests(unittest.TestCase):
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

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client().get(
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
        _assert_upstream_auth(mock_get)
        _assert_upstream_timeout(mock_get)

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

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client().get(
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
        _assert_upstream_auth(mock_get)
        _assert_upstream_timeout(mock_get)

    def test_playlist_rewrite_preserves_crlf_and_final_line_ending(self):
        upstream_playlist = "#EXTM3U\r\nmain.m3u8?PlaySessionId=session\r\n"
        upstream_response = httpx.Response(
            200,
            content=upstream_playlist.encode("utf-8"),
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

        with patch("backend.src.routers.hls.httpx.get", return_value=upstream_response):
            response = _client().get(
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

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client().get(
                "/hls/123/hls1/main0.ts?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].lower(), "video/mp2t")
        self.assertEqual(response.content, b"transport-stream-bytes")
        _assert_upstream_auth(mock_get)
        _assert_upstream_timeout(mock_get)

    def test_request_without_party_session_cookie_is_rejected(self):
        """The URL alone must not be a sufficient credential.

        HLS URLs leak through browser history, Referer, and proxy logs,
        so possession of one is not proof of party membership.
        """
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\r\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client(session=False).get(
                "/hls/123/master.m3u8?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()

    def test_cleared_host_token_locks_the_stream(self):
        """423 once the host's token is gone, not a blanket 401."""
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\r\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )
        no_host = _PartyManager(host_access_token=None)

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client(party_manager=no_host).get(
                "/hls/123/master.m3u8?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 423)
        mock_get.assert_not_called()

    def test_cookie_for_a_different_party_than_the_token_is_rejected(self):
        """Both gates can be satisfied by DIFFERENT parties, so they must agree.

        Otherwise a leaked token for a private party plus a cookie from
        any open party streams the private party's content.
        """
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\r\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )
        two_parties = _PartyManager(known=("PARTY", "OTHER"))

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client(
                party_manager=two_parties, session_party_id="OTHER"
            ).get("/hls/123/master.m3u8?PlaySessionId=session&token=party-token")

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()

    def test_token_for_user_no_longer_in_party_is_rejected(self):
        """Per-user membership, checked beyond the cookie and the party match.

        A token that is otherwise valid, known and unexpired, and whose
        party matches the cookie, must still stop working once its sid is
        no longer a member of that party.
        """
        upstream_response = httpx.Response(
            200,
            text="#EXTM3U\r\n",
            request=httpx.Request("GET", "http://emby.test/master.m3u8"),
        )
        evicted = _PartyManager(users={})

        with patch(
            "backend.src.routers.hls.httpx.get", return_value=upstream_response
        ) as mock_get:
            response = _client(party_manager=evicted).get(
                "/hls/123/master.m3u8?PlaySessionId=session&token=party-token"
            )

        self.assertEqual(response.status_code, 401)
        mock_get.assert_not_called()
