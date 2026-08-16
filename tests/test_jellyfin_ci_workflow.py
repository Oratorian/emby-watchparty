import io
import urllib.error
from pathlib import Path

import yaml

from scripts import run_jellyfin_ci

ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_pinned_real_jellyfin_matrix_and_gates_it() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    job = jobs["jellyfin"]

    assert job["strategy"]["matrix"]["version"] == ["10.10.7", "10.11.11"]
    rendered = workflow_path.read_text(encoding="utf-8")
    assert "jellyfin/jellyfin:${{ matrix.version }}" in rendered
    assert "scripts/run_jellyfin_ci.py" in rendered
    assert "jellyfin-real.spec.ts" in rendered
    assert "if: always()" in rendered
    assert "jellyfin" in jobs["ci-gate"]["needs"]
    assert (ROOT / "scripts" / "run_jellyfin_ci.py").is_file()
    assert (ROOT / "frontend" / "e2e" / "jellyfin-real.spec.ts").is_file()
    journey = (ROOT / "frontend" / "e2e" / "jellyfin-real.spec.ts").read_text(encoding="utf-8")
    assert "response.url()).pathname" not in journey
    runner = (ROOT / "scripts" / "run_jellyfin_ci.py").read_text(encoding="utf-8")
    assert 'video = media / "Synthetic HLS.mp4"' in runner


def test_real_jellyfin_wait_tolerates_transient_non_json_http_errors(monkeypatch) -> None:
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8097/System/Info/Public",
        503,
        "starting",
        {},
        io.BytesIO(b"server starting"),
    )

    def fail(_request, timeout):
        del timeout
        raise error

    monkeypatch.setattr(run_jellyfin_ci.urllib.request, "urlopen", fail)

    assert run_jellyfin_ci._request(error.url) == (503, "server starting")


def test_real_jellyfin_wait_requires_api_json_not_startup_html(monkeypatch) -> None:
    responses = iter(((200, "<html>still starting</html>"), (200, {"Version": "10.11.11"})))
    calls = 0

    def request(_url):
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(run_jellyfin_ci, "_request", request)
    monkeypatch.setattr(run_jellyfin_ci.time, "sleep", lambda _seconds: None)

    run_jellyfin_ci._wait("http://127.0.0.1:8097/System/Info/Public")

    assert calls == 2


def test_real_jellyfin_setup_initializes_first_user_before_updating_it(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def request(url, *, method="GET", body=None, token=None):
        del body, token
        calls.append((method, url))
        return 200, {"Name": "root"}

    monkeypatch.setattr(run_jellyfin_ci, "_request", request)

    run_jellyfin_ci._configure_startup("http://127.0.0.1:8097")

    user_calls = [call for call in calls if call[1].endswith("/Startup/User")]
    assert user_calls == [
        ("GET", "http://127.0.0.1:8097/Startup/User"),
        ("POST", "http://127.0.0.1:8097/Startup/User"),
    ]


def test_real_jellyfin_requests_identify_the_ci_client(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    def open_request(request, timeout):
        del timeout
        captured["authorization"] = request.get_header("X-emby-authorization")
        return Response()

    monkeypatch.setattr(run_jellyfin_ci.urllib.request, "urlopen", open_request)

    run_jellyfin_ci._request("http://127.0.0.1:8097/System/Info/Public")

    assert captured["authorization"].startswith('MediaBrowser Client="emby-watchparty-ci"')
