import copy
import io
import urllib.error
import urllib.parse
from pathlib import Path

import pytest
import yaml

from scripts import require_release_ci

REPOSITORY = "Oratorian/emby-watchparty"
SHA = "a" * 40
OTHER_SHA = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


def run_result(run_id=10, **changes):
    return {
        "id": run_id,
        "head_sha": SHA,
        "event": "push",
        "head_branch": "main",
        "path": ".github/workflows/ci.yml@main",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        **changes,
    }


def gate_result(**changes):
    return {
        "name": "CI Gate",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        **changes,
    }


class FakeAPI:
    def __init__(self, polls=None, jobs=None):
        self.polls = polls if polls is not None else [[run_result()]]
        self.jobs = jobs if jobs is not None else [gate_result()]
        self.poll = -1
        self.calls = []

    def get(self, path, query=None):
        query = query or {}
        self.calls.append((path, query))
        page = query.get("page", 1)
        if path == "actions/workflows/ci.yml/runs":
            if page == 1:
                self.poll += 1
            records = self.polls[min(self.poll, len(self.polls) - 1)]
            key = "workflow_runs"
        elif path.endswith("/jobs"):
            records = self.jobs
            key = "jobs"
        else:
            raise AssertionError(f"Unexpected API request: {path}")
        return {key: copy.deepcopy(records[(page - 1) * 100 : page * 100])}


def check(api, **options):
    return require_release_ci.require_successful_ci(
        api, REPOSITORY, SHA, wait_seconds=options.pop("wait_seconds", 0), **options
    )


def test_reuses_exact_commit_and_current_attempt_gate():
    api = FakeAPI()

    assert check(api)["id"] == 10
    assert api.calls == [
        (
            "actions/workflows/ci.yml/runs",
            {"head_sha": SHA, "event": "push", "per_page": 100, "page": 1},
        ),
        ("actions/runs/10/attempts/2/jobs", {"per_page": 100, "page": 1}),
    ]


@pytest.mark.parametrize("branch", ["main", "3.0-dev"])
@pytest.mark.parametrize("suffix", ["", "@main", "@refs/heads/main"])
def test_accepts_trusted_branches_case_insensitive_repository_and_workflow_ref(branch, suffix):
    result = run_result(
        head_branch=branch,
        path=f".github/workflows/ci.yml{suffix}",
        repository={"full_name": REPOSITORY.upper()},
        head_repository={"full_name": REPOSITORY.lower()},
    )

    assert check(FakeAPI([[result]]))["id"] == 10


@pytest.mark.parametrize(
    "changes",
    [
        {"head_sha": OTHER_SHA},
        {"event": "pull_request"},
        {"event": "workflow_call"},
        {"head_branch": "feat/unreviewed"},
        {"path": ".github/workflows/other.yml@main"},
        {"path": ".github/workflows/ci.yml-copy@main"},
        {"repository": {"full_name": "someone/emby-watchparty"}},
        {"head_repository": {"full_name": "someone/emby-watchparty"}},
        {"head_repository": None},
    ],
)
def test_rejects_unrelated_or_untrusted_runs(changes):
    api = FakeAPI([[run_result(**changes)]])

    with pytest.raises(require_release_ci.CIValidationError, match="No trusted Validate"):
        check(api)
    assert len(api.calls) == 1


def test_untrusted_newer_run_cannot_authorize_or_hide_the_trusted_result():
    api = FakeAPI([[run_result(100, event="pull_request"), run_result(12)]])

    assert check(api)["id"] == 12


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", None])
def test_newer_unsuccessful_run_cannot_be_hidden_by_older_success(conclusion):
    api = FakeAPI([[run_result(20), run_result(100, conclusion=conclusion), run_result(5)]])

    with pytest.raises(require_release_ci.CIValidationError, match="did not succeed"):
        check(api)
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "jobs",
    [
        [],
        [gate_result(name="ci gate")],
        [gate_result(status="queued", conclusion=None)],
        [gate_result(conclusion="failure")],
        [gate_result(conclusion="skipped")],
        [gate_result(head_sha=OTHER_SHA)],
        [gate_result(), gate_result()],
    ],
)
def test_successful_workflow_still_requires_one_successful_exact_commit_gate(jobs):
    with pytest.raises(require_release_ci.CIValidationError, match="no successful CI Gate"):
        check(FakeAPI(jobs=jobs))


def test_gate_from_an_older_attempt_does_not_override_the_current_attempt():
    api = FakeAPI([[run_result(run_attempt=3)]], [gate_result(conclusion="failure")])

    with pytest.raises(require_release_ci.CIValidationError, match="attempt 3"):
        check(api)
    assert api.calls[-1][0] == "actions/runs/10/attempts/3/jobs"


def test_reads_additional_pages_of_runs_and_gate_jobs():
    unrelated = [run_result(index + 100, head_branch="feature") for index in range(100)]
    other_jobs = [gate_result(name=f"Other check {index}") for index in range(100)]
    api = FakeAPI([[*unrelated, run_result(1)]], [*other_jobs, gate_result()])

    assert check(api)["id"] == 1
    assert [query["page"] for _, query in api.calls] == [1, 2, 1, 2]


def fake_clock(monkeypatch):
    elapsed = [0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    monkeypatch.setattr(require_release_ci.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(require_release_ci.time, "sleep", sleep)
    return elapsed, sleeps


def test_waits_for_existing_run_without_restarting_tests(monkeypatch):
    _, sleeps = fake_clock(monkeypatch)
    api = FakeAPI(
        [
            [run_result(status="queued", conclusion=None)],
            [run_result(status="in_progress", conclusion=None)],
            [run_result()],
        ]
    )

    assert check(api, wait_seconds=10, poll_seconds=1)["id"] == 10
    assert sleeps == [1, 1]
    assert api.poll == 2


def test_newer_failure_during_wait_blocks_release(monkeypatch):
    fake_clock(monkeypatch)
    api = FakeAPI(
        [
            [run_result(status="in_progress", conclusion=None)],
            [run_result(), run_result(20, conclusion="failure")],
        ]
    )

    with pytest.raises(require_release_ci.CIValidationError, match="did not succeed"):
        check(api, wait_seconds=10, poll_seconds=1)


def test_pending_run_wait_has_a_bounded_timeout(monkeypatch):
    elapsed, sleeps = fake_clock(monkeypatch)
    api = FakeAPI([[run_result(status="in_progress", conclusion=None)]])

    with pytest.raises(require_release_ci.CIValidationError, match="Timed out"):
        check(api, wait_seconds=3, poll_seconds=15)
    assert elapsed[0] == 3
    assert sleeps == [3]
    assert not any(path.endswith("/jobs") for path, _ in api.calls)


@pytest.mark.parametrize("sha", ["", "abc", OTHER_SHA + "x", "A" * 40, "../main"])
def test_invalid_commit_identifiers_fail_before_api_access(sha):
    api = FakeAPI()

    with pytest.raises(require_release_ci.CIValidationError, match="full commit SHA"):
        require_release_ci.require_successful_ci(api, REPOSITORY, sha)
    assert api.calls == []


@pytest.mark.parametrize("value", [0, -1, "10", True, None])
def test_invalid_run_identifiers_fail_closed(value):
    with pytest.raises(require_release_ci.CIValidationError, match="invalid run identifier"):
        check(FakeAPI([[run_result(value)]]))


@pytest.mark.parametrize("value", [0, -1, "2", True, None])
def test_invalid_run_attempts_fail_closed(value):
    with pytest.raises(require_release_ci.CIValidationError, match="invalid run identifier"):
        check(FakeAPI([[run_result(run_attempt=value)]]))


def test_api_uses_actions_read_headers_and_encodes_query(monkeypatch):
    captured = {}

    def open_request(request, timeout):
        captured["url"] = urllib.parse.urlsplit(request.full_url)
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return io.BytesIO(b'{"workflow_runs": []}')

    monkeypatch.setattr(require_release_ci.urllib.request, "urlopen", open_request)
    api = require_release_ci.GitHubAPI(REPOSITORY, "test-token")

    assert api.get("actions/workflows/ci.yml/runs", {"head_sha": SHA, "event": "push"}) == {
        "workflow_runs": []
    }
    assert captured["url"].scheme == "https"
    assert captured["url"].netloc == "api.github.com"
    assert captured["url"].path == f"/repos/{REPOSITORY}/actions/workflows/ci.yml/runs"
    assert urllib.parse.parse_qs(captured["url"].query) == {
        "head_sha": [SHA],
        "event": ["push"],
    }
    assert captured["authorization"] == "Bearer test-token"
    assert captured["timeout"] == 30


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://api.github.com/private-detail", 403, "private", {}, None),
        urllib.error.URLError("private parser detail"),
        TimeoutError("private timeout detail"),
        ValueError("private JSON detail"),
    ],
)
def test_api_errors_do_not_expose_credentials_or_internal_details(monkeypatch, error):
    def fail(_request, **_kwargs):
        raise error

    monkeypatch.setattr(require_release_ci.urllib.request, "urlopen", fail)

    with pytest.raises(require_release_ci.CIValidationError) as result:
        require_release_ci.GitHubAPI(REPOSITORY, "test-token").get("actions/workflows/ci.yml/runs")
    assert "test-token" not in str(result.value)
    assert "private" not in str(result.value)


def test_cli_emits_pinned_commit_and_summary_only_after_success(tmp_path, monkeypatch, capsys):
    output = tmp_path / "outputs"
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(require_release_ci, "GitHubAPI", lambda _repository, _token: FakeAPI())

    assert require_release_ci.main(["--sha", SHA, "--wait-seconds", "0"]) == 0
    run_url = f"https://github.com/{REPOSITORY}/actions/runs/10"
    assert output.read_text(encoding="utf-8") == f"sha={SHA}\nrun_url={run_url}\n"
    assert SHA in summary.read_text(encoding="utf-8")
    assert run_url in summary.read_text(encoding="utf-8")
    assert "test-token" not in capsys.readouterr().out


def test_cli_failure_preserves_existing_outputs_and_summary(tmp_path, monkeypatch, capsys):
    output = tmp_path / "outputs"
    summary = tmp_path / "summary"
    output.write_text("existing=safe\n", encoding="utf-8")
    summary.write_text("Existing summary\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(require_release_ci, "GitHubAPI", lambda _repository, _token: FakeAPI([[]]))

    assert require_release_ci.main(["--sha", SHA, "--wait-seconds", "0"]) == 1
    assert output.read_text(encoding="utf-8") == "existing=safe\n"
    assert summary.read_text(encoding="utf-8") == "Existing summary\n"
    assert "No trusted Validate" in capsys.readouterr().err


def test_cli_requires_an_actions_token_without_querying_github(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert require_release_ci.main(["--sha", SHA]) == 1
    assert "GITHUB_TOKEN is required" in capsys.readouterr().err


def test_release_reuses_ci_and_publishes_only_the_verified_commit():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    validation = workflow["jobs"]["validate"]
    publishing = workflow["jobs"]["build-and-release"]

    assert "uses" not in validation
    assert validation["permissions"] == {"contents": "read", "actions": "read"}
    assert validation["timeout-minutes"] == 35
    assert validation["outputs"]["sha"] == "${{ steps.validation.outputs.sha }}"
    assert any("HEAD^{commit}" in step.get("run", "") for step in validation["steps"])
    assert any(
        "scripts/require_release_ci.py" in step.get("run", "") for step in validation["steps"]
    )
    assert publishing["needs"] == "validate"
    assert publishing["environment"] == "release"
    assert publishing["permissions"] == {"contents": "write", "packages": "write"}
    assert publishing["steps"][0]["with"]["ref"] == "${{ needs.validate.outputs.sha }}"
