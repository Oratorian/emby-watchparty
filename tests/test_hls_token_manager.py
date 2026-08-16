import logging

from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.hls_token_manager import HLSTokenManager, attach_hls_token
from tests.support.credentials import TEST_SESSION_SECRET


def _config() -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(ENABLE_HLS_TOKEN_VALIDATION=True, HLS_TOKEN_EXPIRY=3600),
    )


def test_tokens_are_bounded_and_revocable_per_user():
    manager = HLSTokenManager(_config(), logging.getLogger("test"), max_tokens=2)
    first = manager.generate("PARTY", "sid-1")
    second = manager.generate("PARTY", "sid-2")
    third = manager.generate("PARTY", "sid-3")

    assert manager.active_token_count == 2
    assert manager.get_party_id(first) is None
    assert manager.get_party_id(second) == "PARTY"
    assert manager.get_party_id(third) == "PARTY"
    assert manager.revoke_user("PARTY", "sid-2") == 1
    assert manager.get_party_id(second) is None


def test_hls_token_uses_correct_query_separator():
    assert attach_hls_token("/hls/stream/master.m3u8", "secret") == (
        "/hls/stream/master.m3u8?token=secret"
    )
    assert attach_hls_token("/hls/master.m3u8?VideoCodec=h264", "secret") == (
        "/hls/master.m3u8?VideoCodec=h264&token=secret"
    )
