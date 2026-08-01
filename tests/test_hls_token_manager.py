import logging

from backend.src.hls_token_manager import HLSTokenManager


class _Config:
    ENABLE_HLS_TOKEN_VALIDATION = True
    HLS_TOKEN_EXPIRY = 3600


def test_tokens_are_bounded_and_revocable_per_user():
    manager = HLSTokenManager(_Config(), logging.getLogger("test"), max_tokens=2)
    first = manager.generate("PARTY", "sid-1")
    second = manager.generate("PARTY", "sid-2")
    third = manager.generate("PARTY", "sid-3")

    assert manager.active_token_count == 2
    assert manager.get_party_id(first) is None
    assert manager.get_party_id(second) == "PARTY"
    assert manager.get_party_id(third) == "PARTY"
    assert manager.revoke_user("PARTY", "sid-2") == 1
    assert manager.get_party_id(second) is None
