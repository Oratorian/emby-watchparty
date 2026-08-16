from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_docs_cover_jellyfin_selection_and_hls_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    compose = (ROOT / "docs/deployment/compose.md").read_text(encoding="utf-8")
    combined = f"{readme}\n{compose}"

    assert "MEDIA_SERVER_TYPE=jellyfin" in combined
    assert "JELLYFIN_SERVER_URL" in combined
    assert "JELLYFIN_API_KEY" in combined
    assert "Changing providers requires a restart" in combined
    assert "HLS-only" in combined
    assert "Live TV" in combined
    assert "SyncPlay" in combined
