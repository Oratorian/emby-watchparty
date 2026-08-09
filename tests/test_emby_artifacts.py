import hashlib
import json
from pathlib import Path

ARTIFACT_ROOT = Path(__file__).parent / "artifacts" / "emby" / "4.9.5.0"
REQUIRED_BOUNDARIES = {
    "system-info",
    "libraries",
    "filter-options",
    "containers",
    "audio-layouts",
    "subtitle-codecs",
    "official-ratings",
    "movie-items",
    "movie-detail",
    "series-detail",
    "episode-detail",
    "grouped-search-source",
    "playlists",
    "playback-selection",
    "related-items",
    "trailers",
    "extras",
    "seasons",
    "episodes",
}
PRIVATE_MARKERS = ("api_key", "access_token", "password", "192.168.", "127.0.0.1")


def test_real_emby_artifacts_have_provenance_and_stable_sanitized_content() -> None:
    manifest_path = ARTIFACT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["emby_version"] == "4.9.5.0"
    assert manifest["sanitization"] == "shape-preserving-v1"
    assert {row["boundary"] for row in manifest["artifacts"]} >= REQUIRED_BOUNDARIES

    for row in manifest["artifacts"]:
        artifact_path = ARTIFACT_ROOT / row["file"]
        payload = artifact_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row["sanitized_sha256"]
        decoded = payload.decode("utf-8").lower()
        assert not any(marker in decoded for marker in PRIVATE_MARKERS)
        assert row["method"] in {"GET", "POST"}
        assert row["path"].startswith("/emby/")
        assert set(row["request"]) == {"query", "body"}
        assert row["raw_sha256"]
