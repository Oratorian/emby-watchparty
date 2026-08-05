import logging
import unittest

from backend.src.client_ip import (
    environ_client_ip,
    reset_untrusted_forwarding_warning,
    resolve_client_ip,
)


def _handshake_environ(peer: str | None, forwarded: str = "") -> dict:
    """A Socket.IO environ shaped the way python-engineio builds one.

    REMOTE_ADDR is the literal every async driver writes, not a peer
    address; the connection's real address is only in the ASGI scope.
    """
    environ: dict = {"REMOTE_ADDR": "127.0.0.1"}
    if peer is not None:
        environ["asgi.scope"] = {"type": "websocket", "client": (peer, 54321)}
    if forwarded:
        environ["HTTP_X_FORWARDED_FOR"] = forwarded
    return environ


class SocketEnvironClientIPTests(unittest.TestCase):
    def test_peer_comes_from_the_asgi_scope_not_remote_addr(self):
        assert (
            environ_client_ip(_handshake_environ("203.0.113.10"), trusted_proxy_cidrs=())
            == "203.0.113.10"
        )

    def test_two_callers_do_not_share_one_bucket(self):
        # The defect this closes: REMOTE_ADDR is a constant, so every
        # socket keyed onto the same rate-limit bucket and 30 connects
        # per minute became a deployment-wide cap.
        first = environ_client_ip(_handshake_environ("203.0.113.10"), trusted_proxy_cidrs=())
        second = environ_client_ip(_handshake_environ("198.51.100.7"), trusted_proxy_cidrs=())
        assert first != second

    def test_forwarded_chain_honoured_behind_a_trusted_proxy(self):
        assert (
            environ_client_ip(
                _handshake_environ("10.0.0.3", forwarded="198.51.100.25, 10.0.0.2"),
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )
            == "198.51.100.25"
        )

    def test_untrusted_peer_still_cannot_spoof_forwarded(self):
        assert (
            environ_client_ip(
                _handshake_environ("203.0.113.10", forwarded="198.51.100.25"),
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )
            == "203.0.113.10"
        )

    def test_missing_scope_does_not_fall_back_to_the_shared_constant(self):
        # A non-ASGI driver leaves no scope. Better to key on an
        # obviously-unknown address than to silently reuse the 127.0.0.1
        # literal that caused the collapse in the first place.
        assert environ_client_ip(_handshake_environ(None), trusted_proxy_cidrs=()) == "0.0.0.0"


class ClientIPTests(unittest.TestCase):
    def test_direct_client_cannot_spoof_forwarded_address(self):
        assert (
            resolve_client_ip(
                peer_ip="203.0.113.10",
                x_forwarded_for="198.51.100.25",
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )
            == "203.0.113.10"
        )

    def test_trusted_proxy_chain_resolves_nearest_untrusted_client(self):
        assert (
            resolve_client_ip(
                peer_ip="10.0.0.3",
                x_forwarded_for="198.51.100.25, 10.0.0.2",
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )
            == "198.51.100.25"
        )

    def test_fully_trusted_forwarded_chain_falls_back_to_peer(self):
        assert (
            resolve_client_ip(
                peer_ip="10.0.0.3",
                x_forwarded_for="10.0.0.1, 10.0.0.2",
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )
            == "10.0.0.3"
        )


class UntrustedForwardingWarningTests(unittest.TestCase):
    """The misdeclared-proxy case, which boot validation cannot reach.

    `BEHIND_PROXY=true` with no CIDRs already fails startup, so a running
    server has declared itself direct. Forwarding headers arriving anyway
    mean that declaration is wrong and every viewer is sharing one bucket.
    """

    def setUp(self):
        reset_untrusted_forwarding_warning()

    def test_discarded_forwarded_header_is_reported(self):
        with self.assertLogs("emby-watchparty", level=logging.WARNING) as captured:
            resolve_client_ip(
                peer_ip="203.0.113.10",
                x_forwarded_for="198.51.100.25",
                trusted_proxy_cidrs=(),
            )
        assert "TRUSTED_PROXY_CIDRS" in captured.output[0]
        assert "203.0.113.10" in captured.output[0]

    def test_reported_only_once_per_process(self):
        # /hls runs several requests per second per viewer, so warning per
        # request would reproduce the log flood this project already fixed.
        with self.assertLogs("emby-watchparty", level=logging.WARNING) as captured:
            for _ in range(5):
                resolve_client_ip(
                    peer_ip="203.0.113.10",
                    x_forwarded_for="198.51.100.25",
                    trusted_proxy_cidrs=(),
                )
        assert len(captured.output) == 1

    def test_ordinary_direct_traffic_is_silent(self):
        logger = logging.getLogger("emby-watchparty")
        with self.assertNoLogs(logger, level=logging.WARNING):
            resolve_client_ip(peer_ip="203.0.113.10", x_forwarded_for="", trusted_proxy_cidrs=())

    def test_correctly_configured_proxy_is_silent(self):
        logger = logging.getLogger("emby-watchparty")
        with self.assertNoLogs(logger, level=logging.WARNING):
            resolve_client_ip(
                peer_ip="10.0.0.3",
                x_forwarded_for="198.51.100.25, 10.0.0.2",
                trusted_proxy_cidrs=("10.0.0.0/8",),
            )

    def test_socket_handshakes_report_it_too(self):
        # #52's lesson: a fix applied to one path and not its twin.
        with self.assertLogs("emby-watchparty", level=logging.WARNING) as captured:
            environ_client_ip(
                _handshake_environ("203.0.113.10", forwarded="198.51.100.25"),
                trusted_proxy_cidrs=(),
            )
        assert "TRUSTED_PROXY_CIDRS" in captured.output[0]


if __name__ == "__main__":
    unittest.main()
