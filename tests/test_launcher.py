from pathlib import Path


def test_powershell_launcher_resolves_root_from_script_location() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "start-watchparty.ps1").read_text(encoding="utf-8")

    assert "$watchPartyRoot = $PSScriptRoot" in launcher
    assert "Documents\\Codex" not in launcher
    assert '$watchPartyBaseUrl = "http://localhost:' in launcher
