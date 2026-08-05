import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.credentials import REJECTED_SESSION_SECRET


def _config(runtime: RuntimeConfig | None = None, **overrides) -> Config:
    values = {
        "WATCH_PARTY_BIND": "0.0.0.0",
        "WATCH_PARTY_PORT": 5000,
        "APP_PREFIX": "",
        "SESSION_EXPIRY": 86400,
        "EMBY_SERVER_URL": "http://emby.test",
        "EMBY_API_KEY": "admin-key",
        "APP_ENV": "production",
        "SESSION_SECRET": "",
        "SESSION_COOKIE_SECURE": True,
        "CORS_ALLOWED_ORIGINS": ("https://watch.example",),
        "TRUSTED_PROXY_CIDRS": (),
        "ENABLE_HLS_TOKEN_VALIDATION": True,
        # Directly exposed, which is the correct pairing with empty
        # TRUSTED_PROXY_CIDRS. Production refuses to boot when the
        # topology is left undeclared, so these cases have to state it
        # even though none of them is about proxying.
        "BEHIND_PROXY": False,
    }
    values.update(overrides)
    return Config(EnvConfig(**values), runtime or RuntimeConfig())


class UpstreamHostnameTests(unittest.TestCase):
    """`EMBY_SERVER_URL` addresses a container, not a public host.

    Docker Compose service and container names may contain underscores and
    Docker's embedded DNS resolves them, so rejecting them stranded anyone
    whose Emby container is named `emby_server`, in unconfigured mode.
    """

    def test_underscored_service_name_is_accepted(self):
        _config(
            SESSION_SECRET="s" * 32,
            EMBY_SERVER_URL="http://emby_server:8096",
        ).validate_for_startup()

    def test_underscored_host_still_rejected_for_cors_origins(self):
        # A browser cannot originate from an underscored host, so the
        # allowlist keeps the strict RFC 1123 form.
        errors = _config(
            SESSION_SECRET="s" * 32,
            CORS_ALLOWED_ORIGINS=("https://watch_party.example",),
        ).startup_errors()
        assert "CORS_ALLOWED_ORIGINS" in errors

    def test_surrounding_whitespace_is_stripped_from_upstream_values(self):
        # A trailing space in a Docker environment variable is invisible in
        # every management UI this project targets. SESSION_SECRET was
        # already stripped; these two were not, so the space reached the
        # URL validator and the Emby auth header.
        with (
            tempfile.TemporaryDirectory() as root,
            mock.patch.dict(
                os.environ,
                {"EMBY_SERVER_URL": "  http://emby.test  ", "EMBY_API_KEY": "  admin-key  "},
            ),
        ):
            config = Config.from_env(project_root=Path(root))
        assert config.EMBY_SERVER_URL == "http://emby.test"
        assert config.EMBY_API_KEY == "admin-key"

    def test_genuinely_malformed_upstream_url_still_rejected(self):
        errors = _config(
            SESSION_SECRET="s" * 32,
            EMBY_SERVER_URL="http://emby server:8096",
        ).startup_errors()
        assert "EMBY_SERVER_URL" in errors


class ProxyTopologyGateTests(unittest.TestCase):
    """Rate limiting keys on the connecting address.

    Behind a reverse proxy that is the proxy for every viewer, so without
    TRUSTED_PROXY_CIDRS the whole deployment shares one bucket. An empty
    CIDR list is nonetheless *correct* for a directly exposed server, so
    emptiness alone cannot be an error. The operator has to state which
    they are, and the contradiction is what gets caught.
    """

    def test_production_requires_the_topology_to_be_declared(self):
        with pytest.raises(ValueError, match="BEHIND_PROXY"):
            _config(SESSION_SECRET="s" * 32, BEHIND_PROXY=None).validate_for_startup()

    def test_behind_a_proxy_without_trusted_cidrs_is_refused(self):
        with pytest.raises(ValueError, match="TRUSTED_PROXY_CIDRS"):
            _config(
                SESSION_SECRET="s" * 32,
                BEHIND_PROXY=True,
                TRUSTED_PROXY_CIDRS=(),
            ).validate_for_startup()

    def test_behind_a_proxy_with_trusted_cidrs_boots(self):
        _config(
            SESSION_SECRET="s" * 32,
            BEHIND_PROXY=True,
            TRUSTED_PROXY_CIDRS=("172.16.0.0/12",),
        ).validate_for_startup()

    def test_direct_deployment_with_no_cidrs_boots(self):
        # The configuration a naive "empty means misconfigured" rule
        # would have broken: no proxy, so trusting nothing is right.
        _config(
            SESSION_SECRET="s" * 32,
            BEHIND_PROXY=False,
            TRUSTED_PROXY_CIDRS=(),
        ).validate_for_startup()

    def test_contradiction_is_refused_outside_production_too(self):
        with pytest.raises(ValueError, match="TRUSTED_PROXY_CIDRS"):
            _config(
                APP_ENV="development",
                BEHIND_PROXY=True,
                TRUSTED_PROXY_CIDRS=(),
            ).validate_for_startup()

    def test_development_may_leave_the_topology_undeclared(self):
        # Running it locally is a direct deployment; do not make every
        # dev shell declare a topology it does not have.
        _config(APP_ENV="development", BEHIND_PROXY=None).validate_for_startup()


class ProductionConfigTests(unittest.TestCase):
    def test_production_rejects_missing_session_secret(self):
        with pytest.raises(ValueError, match="SESSION_SECRET"):
            _config().validate_for_startup()

    def test_production_rejects_short_session_secret(self):
        with pytest.raises(ValueError, match="at least 32"):
            _config(SESSION_SECRET=REJECTED_SESSION_SECRET).validate_for_startup()

    def test_production_rejects_invalid_emby_url(self):
        with pytest.raises(ValueError, match="EMBY_SERVER_URL"):
            _config(
                SESSION_SECRET="s" * 32,
                EMBY_SERVER_URL="file:///etc/passwd",
            ).validate_for_startup()

    def test_production_rejects_other_insecure_boot_settings(self):
        cases = [
            (
                {"SESSION_SECRET": "s" * 32, "SESSION_COOKIE_SECURE": False},
                None,
                "SESSION_COOKIE_SECURE",
            ),
            (
                {"SESSION_SECRET": "s" * 32, "CORS_ALLOWED_ORIGINS": ("*",)},
                None,
                "CORS_ALLOWED_ORIGINS",
            ),
            ({"SESSION_SECRET": "s" * 32, "EMBY_API_KEY": ""}, None, "EMBY_API_KEY"),
            (
                {"SESSION_SECRET": "s" * 32, "ENABLE_HLS_TOKEN_VALIDATION": False},
                None,
                "ENABLE_HLS_TOKEN_VALIDATION",
            ),
        ]
        for env_overrides, runtime, expected in cases:
            with self.subTest(expected=expected), pytest.raises(ValueError, match=expected):
                _config(runtime=runtime, **env_overrides).validate_for_startup()

    def test_development_keeps_localhost_friendly_defaults(self):
        _config(
            APP_ENV="development",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            EMBY_API_KEY="",
        ).validate_for_startup()

    def test_hls_validation_is_rejected_as_runtime_update(self):
        config = _config(SESSION_SECRET="s" * 32)

        changed, rejected = config.update_runtime({"ENABLE_HLS_TOKEN_VALIDATION": False})

        assert changed == []
        assert rejected == [
            {
                "key": "ENABLE_HLS_TOKEN_VALIDATION",
                "reason": "boot setting; restart required",
            }
        ]
        assert config.ENABLE_HLS_TOKEN_VALIDATION is True

    def test_rejects_script_capable_and_ambiguous_app_prefixes(self):
        invalid = (
            "/</script><script>alert(1)</script>",
            "/watch%2fadmin",
            "/watch//admin",
            "/watch/../admin",
            "/watch party",
            "/watch?next=/admin",
            "/" + "a" * 256,
        )
        for prefix in invalid:
            with self.subTest(prefix=prefix):
                errors = _config(SESSION_SECRET="s" * 32, APP_PREFIX=prefix).startup_errors()
                assert "APP_PREFIX" in errors

    def test_requires_exact_cors_origins(self):
        invalid = (
            "https://watch.example/",
            "https://watch.example/path",
            "https://*.example.com",
            "https://user:password@watch.example",
            "https://watch.example?query=yes",
            "https://watch.example#fragment",
            "https://watch.example:notaport",
            "https://watch.example:99999",
            "https://[invalid",
            "https://not_a_host.example",
        )
        for origin in invalid:
            with self.subTest(origin=origin):
                errors = _config(
                    SESSION_SECRET="s" * 32,
                    CORS_ALLOWED_ORIGINS=(origin,),
                ).startup_errors()
                assert "CORS_ALLOWED_ORIGINS" in errors

        for origin in ("https://watch.example", "http://localhost:4173"):
            with self.subTest(valid_origin=origin):
                _config(
                    SESSION_SECRET="s" * 32,
                    CORS_ALLOWED_ORIGINS=(origin,),
                ).validate_for_startup()

    def test_fully_validates_emby_url_while_allowing_base_paths(self):
        invalid = (
            "https://emby.example:notaport",
            "https://emby.example:99999",
            "https://user:password@emby.example",
            "https://*.example.com",
            "https://emby.example/path?query=yes",
            "https://emby.example/path#fragment",
            "https://[invalid",
            # "https://not_a_host.example" used to sit here. Underscored
            # hosts are legitimate upstream addresses, because Docker
            # Compose service names may contain them and Docker's embedded
            # DNS resolves them. Asserted valid in UpstreamHostnameTests,
            # and still rejected for CORS origins, which are browser-facing.
            "https://emby.example\\admin",
        )
        for url in invalid:
            with self.subTest(url=url):
                errors = _config(
                    SESSION_SECRET="s" * 32,
                    EMBY_SERVER_URL=url,
                ).startup_errors()
                assert "EMBY_SERVER_URL" in errors

        _config(
            SESSION_SECRET="s" * 32,
            EMBY_SERVER_URL="https://emby.example/media/emby/",
        ).validate_for_startup()


if __name__ == "__main__":
    unittest.main()
