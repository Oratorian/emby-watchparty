"""Require existing successful push CI for the exact commit being released."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

WORKFLOW = ".github/workflows/ci.yml"
TRUSTED_BRANCHES = {"main", "3.0-dev"}
PENDING_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


class CIValidationError(RuntimeError):
    """The existing CI evidence does not authorize this release."""


class GitHubAPI:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise CIValidationError("GITHUB_REPOSITORY must identify an owner/repository.")
        self.repository = repository
        self.token = token

    def get(self, path: str, query: dict[str, str | int] | None = None) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{self.repository}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - fixed GitHub HTTPS host
        try:
            # Only fixed GitHub REST paths on api.github.com are used here.
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                data = json.load(response)
        except urllib.error.HTTPError as error:
            raise CIValidationError(
                f"GitHub Actions lookup failed (HTTP {error.code}). "
                "Check repository access and the validation job's actions: read permission."
            ) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise CIValidationError(
                "Could not read GitHub Actions results. Retry when the API is available."
            ) from None
        if not isinstance(data, dict):
            raise CIValidationError("GitHub Actions returned an invalid response.")
        return data


def _pages(
    api: GitHubAPI,
    path: str,
    key: str,
    query: dict[str, str | int] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for page in range(1, 101):
        data = api.get(path, {**(query or {}), "per_page": 100, "page": page})
        items = data.get(key)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise CIValidationError("GitHub Actions returned an invalid result list.")
        results.extend(items)
        if len(items) < 100:
            return results
    raise CIValidationError("Too many GitHub Actions results to verify this release safely.")


def _trusted_run(run: dict[str, Any], repository: str, sha: str) -> bool:
    return (
        run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("head_branch") in TRUSTED_BRANCHES
        and str(run.get("path", "")).split("@", 1)[0] == WORKFLOW
        and (run.get("repository") or {}).get("full_name", "").casefold() == repository.casefold()
        and (run.get("head_repository") or {}).get("full_name", "").casefold()
        == repository.casefold()
    )


def _positive_id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise CIValidationError("GitHub Actions returned an invalid run identifier or attempt.")
    return value


def require_successful_ci(
    api: GitHubAPI,
    repository: str,
    sha: str,
    *,
    wait_seconds: float = 1800,
    poll_seconds: float = 15,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise CIValidationError("Release SHA must be a full commit SHA.")
    if wait_seconds < 0 or poll_seconds <= 0:
        raise CIValidationError("CI wait must be nonnegative and polling must be positive.")
    deadline = time.monotonic() + wait_seconds
    while True:
        runs = _pages(
            api,
            "actions/workflows/ci.yml/runs",
            "workflow_runs",
            {"head_sha": sha, "event": "push"},
        )
        candidates = [run for run in runs if _trusted_run(run, repository, sha)]
        if not candidates:
            raise CIValidationError(
                f"No trusted Validate push run exists for {sha}. "
                "Push this commit to main or 3.0-dev, let Validate finish, then retry the release. "
                "Pull-request checks and results for other commits do not qualify."
            )
        # Select before checking success so a newer failed run cannot be hidden
        # by an older green result. Reruns retain the ID and update run_attempt.
        run = max(candidates, key=lambda item: _positive_id(item.get("id")))
        run_id = _positive_id(run.get("id"))
        run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
        status = run.get("status")
        if status == "completed":
            if run.get("conclusion") != "success":
                raise CIValidationError(
                    f"Validate did not succeed for {sha}: {run_url}. "
                    "Fix or rerun Validate before retrying the release."
                )
            attempt = _positive_id(run.get("run_attempt"))
            jobs = _pages(api, f"actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
            gates = [job for job in jobs if job.get("name") == "CI Gate"]
            if len(gates) != 1 or any(
                job.get("status") != "completed"
                or job.get("conclusion") != "success"
                or job.get("head_sha") != sha
                for job in gates
            ):
                raise CIValidationError(
                    f"Validate has no successful CI Gate in attempt {attempt}: {run_url}. "
                    "Complete Validate before retrying the release."
                )
            return run
        if status not in PENDING_STATUSES:
            raise CIValidationError(f"Validate has an unsupported status: {run_url}.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CIValidationError(
                f"Timed out waiting for Validate: {run_url}. "
                "Let it finish, then retry the release; no tests were restarted."
            )
        print(f"Waiting for existing Validate run: {run_url} ({status})", flush=True)
        time.sleep(min(poll_seconds, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--wait-seconds", type=float, default=1800)
    args = parser.parse_args(argv)
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        if not token:
            raise CIValidationError("GITHUB_TOKEN is required to read existing CI results.")
        api = GitHubAPI(repository, token)
        run = require_successful_ci(api, repository, args.sha, wait_seconds=args.wait_seconds)
    except CIValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    run_url = f"https://github.com/{repository}/actions/runs/{run['id']}"
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"sha={args.sha}\nrun_url={run_url}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(
                f"Release commit: `{args.sha}`\n\nValidated by [Validate]({run_url}), including CI Gate. No tests were rerun.\n"
            )
    print(f"Reusing successful Validate results for {args.sha}: {run_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
