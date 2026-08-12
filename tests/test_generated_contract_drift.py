"""The checked-in generated contracts must match what the models render.

Both generators have a `--check` mode, and until now the only thing that ran
it was a single CI step. That left a real hole: pytest passes locally, the
branch looks green, and the drift is only discovered on push -- or not at all,
if the CI step is reordered, renamed or skipped.

It also left a specific mutation undetectable. Removing an event from
INBOUND_MODELS / OUTBOUND_MODELS changes both the models and what `render()`
produces, so every test that asserts on freshly rendered output still agrees
with itself. Only a comparison against the file on disk notices that the
frontend is still typed for an event the backend no longer accepts.

Running the same check here means the failure lands next to the change that
caused it, with the command to fix it.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GENERATORS = (
    ("socket events", "scripts/generate_socket_types.py"),
    ("REST schema", "scripts/generate_openapi_types.py"),
)


def _check(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, repo-local script
        [sys.executable, script, "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_the_generated_socket_contract_is_not_stale() -> None:
    result = _check("scripts/generate_socket_types.py")
    assert result.returncode == 0, (
        "backend/socket-events.schema.json or frontend/src/types/socket.generated.ts "
        "no longer matches the Pydantic models. Run "
        "`python scripts/generate_socket_types.py` and commit the result.\n"
        f"{result.stdout}{result.stderr}"
    )


def test_the_generated_rest_contract_is_not_stale() -> None:
    result = _check("scripts/generate_openapi_types.py")
    assert result.returncode == 0, (
        "frontend/src/types/api.generated.ts no longer matches the FastAPI routes. "
        "Run `python scripts/generate_openapi_types.py` and commit the result.\n"
        f"{result.stdout}{result.stderr}"
    )


def test_both_generators_still_have_a_check_mode() -> None:
    """The tests above would pass vacuously against a generator that ignores it."""
    for label, script in GENERATORS:
        source = (REPO_ROOT / script).read_text(encoding="utf-8")
        assert '"--check"' in source, f"{label} generator lost its --check flag"
