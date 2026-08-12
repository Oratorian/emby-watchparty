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
    python_report = tmp_path / "coverage.xml"
    python_report.write_text(
        """<?xml version="1.0" ?>
<coverage><packages><package><classes>
  <class filename="backend/example.py"><lines>
    <line number="1" hits="1"/><line number="2" hits="0"/>
  </lines></class>
</classes></package></packages></coverage>
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
        ]
    )

    assert result == 1
    assert "Changed-line coverage: 2/3 (66.67%); required: 80.00%" in capsys.readouterr().out


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
