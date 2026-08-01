import unittest

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
    }
    values.update(overrides)
    return Config(EnvConfig(**values), runtime or RuntimeConfig())


class ProductionConfigTests(unittest.TestCase):
    def test_production_rejects_missing_session_secret(self):
        with self.assertRaisesRegex(ValueError, "SESSION_SECRET"):
            _config().validate_for_startup()

    def test_production_rejects_other_insecure_boot_settings(self):
        cases = [
            ({"SESSION_SECRET": "stable", "SESSION_COOKIE_SECURE": False}, None,
             "SESSION_COOKIE_SECURE"),
            ({"SESSION_SECRET": "stable", "CORS_ALLOWED_ORIGINS": ("*",)}, None,
             "CORS_ALLOWED_ORIGINS"),
            ({"SESSION_SECRET": "stable", "EMBY_API_KEY": ""}, None,
             "EMBY_API_KEY"),
            ({"SESSION_SECRET": "stable"}, RuntimeConfig(ENABLE_HLS_TOKEN_VALIDATION=False),
             "HLS token validation"),
        ]
        for env_overrides, runtime, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    _config(runtime=runtime, **env_overrides).validate_for_startup()

    def test_development_keeps_localhost_friendly_defaults(self):
        _config(
            APP_ENV="development",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            EMBY_API_KEY="",
        ).validate_for_startup()


if __name__ == "__main__":
    unittest.main()
