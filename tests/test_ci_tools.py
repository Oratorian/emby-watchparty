from pathlib import Path

from scripts.check_diff_coverage import main as coverage_main
from scripts.validate_trivy_ignores import main as trivy_ignores_main


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
+prefix = "++ not a header"
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
