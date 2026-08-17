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
        "MEDIA_SERVER_TYPE": "emby",
        "MEDIA_SERVER_URL": "http://emby.test",
        "MEDIA_SERVER_API_KEY": "admin-key",
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


def test_failed_runtime_save_rolls_back_every_field_type() -> None:
    runtime = RuntimeConfig(
        STATIC_SESSION_ENABLED=False,
        STATIC_SESSION_ID="PARTY",
        LOG_MAX_SIZE=10,
        ENABLED_QUALITY_OPTIONS={"720p": [4000]},
    )
    config = _config(runtime=runtime)
    before = runtime.to_dict()

    with (
        mock.patch.object(RuntimeConfig, "save", side_effect=OSError("read-only config")),
        pytest.raises(OSError, match="read-only config"),
    ):
        config.update_runtime(
            {
                "STATIC_SESSION_ENABLED": True,
                "STATIC_SESSION_ID": "LOUNGE",
                "LOG_MAX_SIZE": 25,
                "ENABLED_QUALITY_OPTIONS": {"1080p": [10000, 8000]},
            }
        )

    assert runtime.to_dict() == before


class UpstreamHostnameTests(unittest.TestCase):
    """`MEDIA_SERVER_URL` addresses a container, not a public host.

    Docker Compose service and container names may contain underscores and
    Docker's embedded DNS resolves them, so rejecting them stranded anyone
    whose Emby container is named `emby_server`, in unconfigured mode.
    """

    def test_underscored_service_name_is_accepted(self):
        _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_URL="http://emby_server:8096",
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
        # URL validator and the upstream auth header.
        with (
            tempfile.TemporaryDirectory() as root,
            mock.patch.dict(
                os.environ,
                {
                    "MEDIA_SERVER_URL": "  http://emby.test  ",
                    "MEDIA_SERVER_API_KEY": "  admin-key  ",
                },
            ),
        ):
            config = Config.from_env(project_root=Path(root))
        assert config.MEDIA_SERVER_URL == "http://emby.test"
        assert config.MEDIA_SERVER_API_KEY == "admin-key"

    def test_genuinely_malformed_upstream_url_still_rejected(self):
        errors = _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_URL="http://emby server:8096",
        ).startup_errors()
        assert "MEDIA_SERVER_URL" in errors


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


class LegacyBootPrecedenceTests(unittest.TestCase):
    def test_hls_validation_uses_environment_then_dotenv_then_legacy_then_default(
        self,
    ):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            config_path = root / "config.json"

            with mock.patch.dict(os.environ, {}, clear=True):
                assert Config.from_env(root).ENABLE_HLS_TOKEN_VALIDATION is True

                config_path.write_text('{"ENABLE_HLS_TOKEN_VALIDATION": false}', encoding="utf-8")
                assert Config.from_env(root).ENABLE_HLS_TOKEN_VALIDATION is False

                (root / ".env").write_text("ENABLE_HLS_TOKEN_VALIDATION=true\n", encoding="utf-8")
                assert Config.from_env(root).ENABLE_HLS_TOKEN_VALIDATION is True

                with mock.patch.dict(os.environ, {"ENABLE_HLS_TOKEN_VALIDATION": "false"}):
                    assert Config.from_env(root).ENABLE_HLS_TOKEN_VALIDATION is False


class RetiredProviderFieldTests(unittest.TestCase):
    """3.0 consolidated four provider variables into two, with no aliases.

    Reading a retired name as a fallback would have looked kinder and been
    worse: the deployment keeps a variable the documentation no longer
    mentions, and on the day the fallback goes away it boots against the
    default localhost URL and serves an empty library with no explanation.
    A boot error naming the replacement is therefore the entire migration
    path, which is why each retired name is asserted on its own.

    These all resolve through a temp project root so a real .env sitting in
    the repo cannot supply a value none of them declared.
    """

    RETIRED_TO_REPLACEMENT = (
        ("EMBY_SERVER_URL", "MEDIA_SERVER_URL"),
        ("JELLYFIN_SERVER_URL", "MEDIA_SERVER_URL"),
        ("EMBY_API_KEY", "MEDIA_SERVER_API_KEY"),
        ("JELLYFIN_API_KEY", "MEDIA_SERVER_API_KEY"),
    )

    def test_each_retired_name_in_the_environment_names_its_replacement(self):
        for retired, replacement in self.RETIRED_TO_REPLACEMENT:
            with (
                self.subTest(retired=retired),
                tempfile.TemporaryDirectory() as raw_root,
                mock.patch.dict(os.environ, {retired: "a-value-from-2.x"}, clear=True),
            ):
                errors = Config.from_env(Path(raw_root)).startup_errors()

                assert errors[retired] == (
                    f"was replaced by {replacement} in 3.0; rename it and remove the old name"
                )

    def test_a_retired_name_in_dotenv_names_its_replacement(self):
        # .env is where an upgrading deployment's old value actually lives.
        # A Compose file or an Unraid template gets re-pulled; the .env the
        # operator hand-edited in 2.x is carried across untouched.
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / ".env").write_text("JELLYFIN_API_KEY=an-old-key\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True):
                errors = Config.from_env(root).startup_errors()

        assert errors["JELLYFIN_API_KEY"] == (
            "was replaced by MEDIA_SERVER_API_KEY in 3.0; rename it and remove the old name"
        )

    def test_a_retired_value_is_never_read_as_a_fallback(self):
        # The signpost is not an alias. With only the retired names set,
        # the new fields resolve to their plain defaults, exactly as if
        # nothing had been declared at all.
        with (
            tempfile.TemporaryDirectory() as raw_root,
            mock.patch.dict(
                os.environ,
                {
                    "EMBY_SERVER_URL": "http://retired-emby.example:8096",
                    "EMBY_API_KEY": "retired-key",
                },
                clear=True,
            ),
        ):
            config = Config.from_env(Path(raw_root))

        assert config.MEDIA_SERVER_URL == "http://localhost:8096"
        assert config.MEDIA_SERVER_API_KEY == ""

    def test_a_retired_name_is_fatal_rather_than_advisory(self):
        # Boot errors are what put the app into unconfigured mode, so this
        # is the difference between "operator is told" and "operator finds
        # out from an empty library".
        with (
            tempfile.TemporaryDirectory() as raw_root,
            mock.patch.dict(
                os.environ,
                {
                    "MEDIA_SERVER_URL": "http://emby.test",
                    "MEDIA_SERVER_API_KEY": "admin-key",
                    "EMBY_SERVER_URL": "http://emby.test",
                },
                clear=True,
            ),
        ):
            config = Config.from_env(Path(raw_root))

        with pytest.raises(ValueError, match="EMBY_SERVER_URL"):
            config.validate_for_startup()

    def test_the_new_names_alone_raise_no_retirement_error(self):
        with (
            tempfile.TemporaryDirectory() as raw_root,
            mock.patch.dict(
                os.environ,
                {
                    "MEDIA_SERVER_TYPE": "jellyfin",
                    "MEDIA_SERVER_URL": "http://jellyfin.test",
                    "MEDIA_SERVER_API_KEY": "jellyfin-key",
                },
                clear=True,
            ),
        ):
            config = Config.from_env(Path(raw_root))

        # The whole dict, not just the absence of the retirement error: a
        # deployment that declares only the two new names is a complete
        # deployment and has to boot clean.
        assert config.startup_errors() == {}
        assert config.MEDIA_SERVER_URL == "http://jellyfin.test"
        assert config.MEDIA_SERVER_API_KEY == "jellyfin-key"


class ProductionConfigTests(unittest.TestCase):
    def test_emby_remains_the_default_media_server(self):
        # Resolved through from_env with nothing declared, because that is
        # where the default now lives: EnvConfig carries no class-level
        # default for MEDIA_SERVER_TYPE, so asserting it on a hand-built
        # EnvConfig would only echo the value the test itself passed.
        with (
            tempfile.TemporaryDirectory() as raw_root,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            config = Config.from_env(Path(raw_root))

        assert config.MEDIA_SERVER_TYPE == "emby"

    def test_jellyfin_reads_the_same_url_and_key_as_emby(self):
        # The address and the credential were never provider-specific, so
        # switching provider is a one-line change to MEDIA_SERVER_TYPE and
        # nothing else. Only the type distinguishes the two.
        config = _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="https://jellyfin.example/base",
            MEDIA_SERVER_API_KEY="jellyfin-key",
        )

        config.validate_for_startup()
        assert config.MEDIA_SERVER_URL == "https://jellyfin.example/base"
        assert config.MEDIA_SERVER_API_KEY == "jellyfin-key"

    def test_missing_url_and_key_are_reported_under_the_shared_names(self):
        # Reported as MEDIA_SERVER_*, whatever the provider: an operator
        # running Jellyfin must not be sent hunting for a JELLYFIN_ prefixed
        # variable that no longer exists.
        errors = _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="",
            MEDIA_SERVER_API_KEY="",
        ).startup_errors()

        assert "MEDIA_SERVER_URL" in errors
        assert "MEDIA_SERVER_API_KEY" in errors

    def test_unknown_media_server_type_is_rejected(self):
        errors = _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_TYPE="plex",
        ).startup_errors()

        assert errors["MEDIA_SERVER_TYPE"] == "must be 'emby' or 'jellyfin'"

    def test_production_rejects_missing_session_secret(self):
        with pytest.raises(ValueError, match="SESSION_SECRET"):
            _config().validate_for_startup()

    def test_production_rejects_short_session_secret(self):
        with pytest.raises(ValueError, match="at least 32"):
            _config(SESSION_SECRET=REJECTED_SESSION_SECRET).validate_for_startup()

    def test_production_rejects_invalid_media_server_url(self):
        with pytest.raises(ValueError, match="MEDIA_SERVER_URL"):
            _config(
                SESSION_SECRET="s" * 32,
                MEDIA_SERVER_URL="file:///etc/passwd",
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
            (
                {"SESSION_SECRET": "s" * 32, "MEDIA_SERVER_API_KEY": ""},
                None,
                "MEDIA_SERVER_API_KEY",
            ),
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
            MEDIA_SERVER_API_KEY="",
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

    def test_fully_validates_media_server_url_while_allowing_base_paths(self):
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
                    MEDIA_SERVER_URL=url,
                ).startup_errors()
                assert "MEDIA_SERVER_URL" in errors

        _config(
            SESSION_SECRET="s" * 32,
            MEDIA_SERVER_URL="https://emby.example/media/emby/",
        ).validate_for_startup()


if __name__ == "__main__":
    unittest.main()
