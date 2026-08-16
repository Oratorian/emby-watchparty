from pathlib import Path

import yaml

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
