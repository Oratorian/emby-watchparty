import os
import re
import shutil
import subprocess
from pathlib import Path

from scripts.check_diff_coverage import main as coverage_main
from scripts.validate_trivy_ignores import main as trivy_ignores_main

ROOT = Path(__file__).resolve().parents[1]


def test_changed_executable_lines_must_meet_threshold(tmp_path: Path, capsys) -> None:
    diff = tmp_path / "changes.diff"
    diff.write_text(
        """diff --git a/backend/example.py b/backend/example.py
--- a/backend/example.py
+++ b/backend/example.py
@@ -0,0 +1,2 @@
+covered = True
+uncovered = False
diff --git a/frontend/src/example.ts b/frontend/src/example.ts
--- a/frontend/src/example.ts
+++ b/frontend/src/example.ts
@@ -0,0 +1 @@
+export const covered = true
""",
        encoding="utf-8",
    )
    # The filename is relative to its <source> root, which is the shape
    # coverage.py actually emits. The previous fixture wrote a repo-relative
    # "backend/example.py", a shape coverage.py never produces, so this test
    # passed while the real gate matched no Python line at all.
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "example.py").write_text("covered = True\n", encoding="utf-8")
    python_report = tmp_path / "coverage.xml"
    python_report.write_text(
        f"""<?xml version="1.0" ?>
<coverage>
  <sources><source>{tmp_path / "backend"}</source></sources>
  <packages><package><classes>
    <class filename="example.py"><lines>
      <line number="1" hits="1"/><line number="2" hits="0"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )
    frontend_report = tmp_path / "lcov.info"
    frontend_report.write_text(
        """SF:src/example.ts
DA:1,1
end_of_record
""",
        encoding="utf-8",
    )

    result = coverage_main(
        [
            "--diff-file",
            str(diff),
            "--python-report",
            str(python_report),
            "--frontend-report",
            str(frontend_report),
            "--threshold",
            "80",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "Changed-line coverage: 2/3 (66.67%); required: 80.00%" in output
    # The Python half must actually be counted. Before the source-root fix the
    # totals here were 1/1 (100%) from the frontend alone and the gate passed.
    assert "python: 2 executable of 2 changed line(s)" in output


def test_generated_check_commands_agree_across_contributor_surfaces() -> None:
    pattern = re.compile(r"python scripts/(generate_[a-z_]+\.py) --check")
    paths = (
        ROOT / "CONTRIBUTING.md",
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
        ROOT / ".github" / "workflows" / "ci.yml",
    )
    command_sets = [set(pattern.findall(path.read_text(encoding="utf-8"))) for path in paths]

    assert "generate_openapi_types.py" in command_sets[0]
    assert command_sets[0] == command_sets[1] == command_sets[2]


def test_added_line_beginning_with_plus_plus_is_not_read_as_a_file_header(
    tmp_path: Path, capsys
) -> None:
    """A diff header is only a header when its `--- ` counterpart precedes it.

    An added line whose own content starts with "++ " reaches the parser as
    "+++ ...". Treating that as a header dropped every remaining hunk in the
    file, so uncovered lines after it stopped counting and the gate drifted
    green.
    """
    diff = tmp_path / "changes.diff"
    diff.write_text(
        """diff --git a/backend/example.py b/backend/example.py
--- a/backend/example.py
+++ b/backend/example.py
@@ -0,0 +1 @@
+++ not a header
@@ -5,0 +6 @@
+uncovered = False
""",
        encoding="utf-8",
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "example.py").write_text("x = 1\n", encoding="utf-8")
    python_report = tmp_path / "coverage.xml"
    python_report.write_text(
        f"""<?xml version="1.0" ?>
<coverage>
  <sources><source>{tmp_path / "backend"}</source></sources>
  <packages><package><classes>
    <class filename="example.py"><lines>
      <line number="1" hits="1"/><line number="6" hits="0"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )
    frontend_report = tmp_path / "lcov.info"
    frontend_report.write_text("", encoding="utf-8")

    result = coverage_main(
        [
            "--diff-file",
            str(diff),
            "--python-report",
            str(python_report),
            "--frontend-report",
            str(frontend_report),
            "--threshold",
            "80",
            "--repo-root",
            str(tmp_path),
        ]
    )

    # Both hunks must be seen. If the second is dropped the run reports 1/1.
    assert result == 1
    assert "Changed-line coverage: 1/2 (50.00%); required: 80.00%" in capsys.readouterr().out


def test_git_diff_is_decoded_as_utf8_from_real_repository(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "repo"
    repo.mkdir()

    # Ignore the contributor's own git config. A global commit.gpgsign or
    # core.hooksPath would otherwise fail the commits below on their machine
    # and nowhere else.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }

    def run_git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # fixed executable and test-controlled argv
            [git, *args],
            cwd=repo,
            check=True,
            capture_output=True,
            encoding="utf-8",
            env=env,
        )

    run_git("init")
    run_git("config", "user.email", "ci-test@example.invalid")
    run_git("config", "user.name", "CI Test")
    fixture = repo / "fixture.py"
    fixture.write_text("title = 'base'\n", encoding="utf-8")
    run_git("add", "fixture.py")
    run_git("commit", "-m", "base")
    base = run_git("rev-parse", "HEAD").stdout.strip()

    # Cyrillic capital A encodes to D0 90. Byte 0x90 is undefined in cp1252,
    # reproducing the Windows decoder crash against Git's real stdout pipe.
    #
    # It has to be committed. The script diffs `<base>...HEAD`, which compares
    # two revisions and never looks at the working tree, so leaving this
    # uncommitted produces an empty diff, decodes nothing, and passes whether
    # or not the fix is present.
    fixture.write_text("title = '\u0410'\n", encoding="utf-8")
    run_git("add", "fixture.py")
    run_git("commit", "-m", "cyrillic")

    python_report = tmp_path / "coverage.xml"
    python_report.write_text(
        f"""<coverage>
  <sources><source>{repo}</source></sources>
  <packages><package><classes>
    <class filename="fixture.py"><lines><line number="1" hits="1"/></lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )
    frontend_report = tmp_path / "lcov.info"
    frontend_report.write_text("", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert (
        coverage_main(
            [
                "--base",
                base,
                "--python-report",
                str(python_report),
                "--frontend-report",
                str(frontend_report),
                "--repo-root",
                str(repo),
            ]
        )
        == 0
    )
    # An empty diff also exits 0, so the return code alone cannot tell a
    # decoded diff from one that was never produced. Pin the changed line.
    assert "python: 1 executable of 1 changed line(s)" in capsys.readouterr().out


def test_changed_line_diff_is_pinned_to_utf8_rather_than_the_ambient_locale(
    tmp_path: Path, monkeypatch
) -> None:
    """The real-git test above cannot fail on a UTF-8 host.

    Every CI runner this repo uses is one, and so is any Windows box in UTF-8
    mode, so that test only ever exercises the bug on a cp1252 machine. This
    one asserts the kwarg directly, which is what keeps a revert to
    `text=True` from passing everywhere the crash cannot be reproduced.
    """
    recorded: dict[str, object] = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):  # type: ignore[no-untyped-def]
        if "diff" in argv:
            recorded.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)

    python_report = tmp_path / "coverage.xml"
    python_report.write_text(
        f"""<coverage>
  <sources><source>{tmp_path}</source></sources>
  <packages><package><classes></classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )
    frontend_report = tmp_path / "lcov.info"
    frontend_report.write_text("", encoding="utf-8")

    coverage_main(
        [
            "--base",
            "HEAD",
            "--python-report",
            str(python_report),
            "--frontend-report",
            str(frontend_report),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert recorded, "the git diff subprocess was never invoked"
    assert recorded.get("encoding") == "utf-8", (
        "check_diff_coverage must decode git's stdout as UTF-8 explicitly, got "
        f"encoding={recorded.get('encoding')!r} text={recorded.get('text')!r}. "
        "text=True defers to locale.getpreferredencoding(False), which is cp1252 "
        "on a default Windows host and raises UnicodeDecodeError on a UTF-8 diff."
    )
    assert not recorded.get("text"), "text=True re-introduces the locale-dependent decode"


def test_vulnerability_exception_requires_owner_reason_and_expiry(tmp_path: Path, capsys) -> None:
    policy = tmp_path / ".trivyignore.yaml"
    policy.write_text(
        """vulnerabilities:
  - id: CVE-2099-0001
    statement: temporary exception
misconfigurations: []
""",
        encoding="utf-8",
    )

    assert trivy_ignores_main(["--file", str(policy)]) == 1
    assert "CVE-2099-0001: expired_at must be a future ISO date" in capsys.readouterr().err


def test_every_trivy_section_requires_owner_and_expiry(tmp_path: Path, capsys) -> None:
    """A suppression must not escape the policy by choosing another heading.

    Only vulnerabilities and misconfigurations were validated, so an entry
    filed under secrets or licenses needed no owner and never expired, while
    Trivy honoured it exactly the same.
    """
    policy = tmp_path / ".trivyignore.yaml"
    policy.write_text(
        """vulnerabilities: []
misconfigurations: []
secrets:
  - id: generic-api-key
    statement: temporary
licenses:
  - id: GPL-3.0
    statement: temporary
""",
        encoding="utf-8",
    )

    assert trivy_ignores_main(["--file", str(policy)]) == 1
    errors = capsys.readouterr().err
    assert "generic-api-key: expired_at must be a future ISO date" in errors
    assert "GPL-3.0: expired_at must be a future ISO date" in errors


def test_a_misspelled_section_is_rejected_rather_than_silently_ignored(
    tmp_path: Path, capsys
) -> None:
    """Trivy ignores an unknown heading too, so the suppression does nothing.

    Without this the file looks like it grants an exception and does not, which
    is worse than either outcome on its own.
    """
    policy = tmp_path / ".trivyignore.yaml"
    policy.write_text("vulnerabilites: []\n", encoding="utf-8")

    assert trivy_ignores_main(["--file", str(policy)]) == 1
    assert "unknown section 'vulnerabilites'" in capsys.readouterr().err
