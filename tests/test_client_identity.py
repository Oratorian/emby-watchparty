"""What Watch Party tells the media server it is.

The `X-Emby-Authorization` header is how Emby and Jellyfin label this client in
their dashboards, session lists and logs. It carried a hardcoded Version="1.0"
from the beginning, so every server on both product lines has been reporting
the wrong version for the entire life of the project, and an operator reading
their own dashboard could not tell a 1.6 install from a 3.0 one.

The literal is the whole hazard here: it is a plausible-looking string sitting
in a header nobody reads back, so nothing fails when it goes stale. These tests
assert it tracks `backend.src.__version__`, and that no literal creeps back.
"""

import re
from pathlib import Path

from backend.src import __version__
from backend.src.emby_client import EmbyClient
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_SOURCE = REPO_ROOT / "backend" / "src" / "emby_client.py"


def _client() -> EmbyClient:
    # The gateway is never touched by header construction.
    return EmbyClient("http://media.test", "api-key", logger=None, gateway=None)


def test_authenticated_requests_report_the_running_version() -> None:
    header = _client()._headers(access_token=TEST_JELLYFIN_ACCESS_TOKEN, user_id="user-1")[
        "X-Emby-Authorization"
    ]

    assert f'Version="{__version__}"' in header
    assert 'Client="WatchParty"' in header


def test_the_login_request_reports_the_running_version() -> None:
    """Login builds its own header, so it is a second place to go stale."""
    client = _client()
    # Mirrors the literal in EmbyClient.authenticate, which cannot be reached
    # without a gateway round trip.
    header = (
        f'Emby Client="WatchParty", Device="Web", '
        f'DeviceId="{client.device_id}", Version="{__version__}"'
    )

    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    assert 'DeviceId="{self.device_id}", Version="{__version__}"' in source
    assert f'Version="{__version__}"' in header


def test_no_hardcoded_client_version_remains() -> None:
    """A literal here is invisible in every test that only checks behaviour.

    Both header sites are f-strings, so a hardcoded version would still produce
    a well-formed header and every other test would stay green.
    """
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    literals = re.findall(r'Version="(\d[^"{]*)"', source)

    assert literals == [], f"hardcoded client version(s) in emby_client.py: {literals}"


def test_the_reported_version_is_the_real_one() -> None:
    """Guards against the header tracking some other, stale constant."""
    init_source = (REPO_ROOT / "backend" / "src" / "__init__.py").read_text(encoding="utf-8")
    declared = re.search(r'^__version__ = "([^"]+)"', init_source, re.M)

    assert declared is not None
    assert declared.group(1) == __version__
