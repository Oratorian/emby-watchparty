import unittest

import pytest

from backend.src.config import Config, EnvConfig, RuntimeConfig


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
    }
    values.update(overrides)
    return Config(EnvConfig(**values), runtime or RuntimeConfig())


class ProductionConfigTests(unittest.TestCase):
    def test_production_rejects_missing_session_secret(self):
        with pytest.raises(ValueError, match="SESSION_SECRET"):
            _config().validate_for_startup()

    def test_production_rejects_short_session_secret(self):
        with pytest.raises(ValueError, match="at least 32"):
            _config(SESSION_SECRET="too-short").validate_for_startup()

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


if __name__ == "__main__":
    unittest.main()
