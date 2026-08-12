"""The identity-collision message is matched on, so its wording is an API.

When a second tab joins under a name the party already has, the backend
answers with a specific sentence and the frontend store matches that sentence
verbatim to decide whether to rotate onto a tab-scoped client id and retry.
Anything else in that field is treated as an ordinary join failure.

So the two literals are one contract written in two languages, and nothing
else keeps them in step: reword the Python and both suites stay green while
the second tab stops recovering and simply fails to join. Asserted from
pytest because it is the only side that can read both files.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROUTE = REPO_ROOT / "backend" / "src" / "routers" / "party.py"
FRONTEND_STORE = REPO_ROOT / "frontend" / "src" / "stores" / "party.ts"


def _frontend_literal() -> str:
    source = FRONTEND_STORE.read_text(encoding="utf-8")
    match = re.search(
        r"const IDENTITY_IN_USE_MESSAGE\s*=\s*['\"](?P<message>[^'\"]+)['\"]",
        source,
    )
    assert match, "IDENTITY_IN_USE_MESSAGE is gone from the party store"
    return match.group("message")


def test_the_backend_still_sends_the_sentence_the_client_matches() -> None:
    message = _frontend_literal()
    route = BACKEND_ROUTE.read_text(encoding="utf-8")

    assert f'message="{message}"' in route, (
        f"The join route no longer answers with {message!r}, which "
        f"{FRONTEND_STORE.name} matches verbatim to trigger the tab-scoped "
        "client-id rotation. Change both or neither."
    )


def test_the_client_is_matching_on_something_specific() -> None:
    """A short or generic sentence would collide with other join failures."""
    message = _frontend_literal()
    assert len(message) > 20
    assert message.lower() not in {"error", "failed", "could not join"}
