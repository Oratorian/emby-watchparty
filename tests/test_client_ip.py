import unittest

from backend.src.client_ip import resolve_client_ip


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


if __name__ == "__main__":
    unittest.main()
