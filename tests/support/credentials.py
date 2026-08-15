"""Credential fixtures shared by the test suite.

The valid secret is generated once per run rather than written as a literal, so
the repository carries no hardcoded credential and no test can quietly come to
depend on one particular value.

The rejected fixtures below stay literal on purpose: being invalid in a specific
way is the whole point of them, so each carries a narrow suppression rather than
the suite-wide exemption these used to rely on.
"""

import secrets

TEST_SESSION_SECRET = secrets.token_hex(32)
"""A valid session secret: 64 hex characters, well over the 32-character minimum."""

TEST_JELLYFIN_ACCESS_TOKEN = secrets.token_urlsafe(24)
"""Opaque fake-server token generated per test run, never a committed credential."""

TEST_HLS_BROWSER_TOKEN = secrets.token_urlsafe(24)
"""Opaque browser HLS token generated per test run."""

# Deliberately below the 32-character minimum, to assert that startup refuses it.
REJECTED_SESSION_SECRET = "short"  # noqa: S105

# Not a real token. Seeded into an admin session to exercise the path where a
# stashed token fails revalidation and the session must be scrubbed.
REVOKED_ACCESS_TOKEN = "revoked-token"  # noqa: S105

# Stands in for the raw Emby admin token that 2.0.2 wrote into the signed
# cookie. Tests assert this exact string is gone from the re-issued cookie,
# so it has to be a literal they can search the decoded payload for.
LEGACY_COOKIE_ADMIN_TOKEN = "legacy-secret"  # noqa: S105
