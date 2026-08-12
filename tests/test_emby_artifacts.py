import hashlib
import json
import re
from collections.abc import Iterator
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
    "resolution-filter",
    "filtered-prefixes",
    "upstream-error",
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
    "favorite-add",
    "favorite-remove",
    "played-add",
    "played-remove",
    "playlist-create",
    "playlist-add",
    "filtered-query-unnamed-folder",
}
PRIVATE_MARKERS = ("api_key", "access_token", "password", "192.168.", "127.0.0.1")

# Matched against the key and EVERY ancestor key, so ProviderIds.Tmdb is
# covered by its parent. Substring matching, mirroring the sanitizer.
PRIVATE_ANCESTORS = ("token", "password", "path", "username", "providerid", "filename")
# Exact key names, deliberately not substrings: DisplayTitle ("1080p HEVC") and
# SubtitleLocationType are semantic values the sanitizer is right to keep, and
# a substring rule on "title"/"name" flags both.
TITLE_KEYS = {
    "Name",
    "SortName",
    "ForcedSortName",
    "OriginalTitle",
    "SeriesName",
    "Album",
    "AlbumArtist",
    "Overview",
    "Tagline",
    "Taglines",
    "FileName",
    "ServerName",
}
# Shapes that betray real content regardless of which key carries them. These
# are the ones that actually shipped: media filenames, an external id that
# re-identifies a title on its own, and the capture machine's hostname.
LEAK_PATTERNS = (
    re.compile(r"\.(mkv|mp4|avi|m4v|mov|ts|m2ts|wmv|flv|mpg|mpeg|iso)$", re.IGNORECASE),
    re.compile(r"^tt\d{6,}$"),
    re.compile(r"^DESKTOP-[A-Z0-9]+$", re.IGNORECASE),
    re.compile(r"^[A-Za-z]:[\\/]"),
)
MANIFEST_BOOKKEEPING = {
    "path",
    "file",
    "boundary",
    "method",
    "raw_sha256",
    "sanitized_sha256",
    "emby_version",
    "sanitization",
}


def _strings(node: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every string leaf, paired with the full key path that reaches it.

    The path matters: ProviderIds is a dict, so its Imdb/Tmdb leaves are only
    recognisable as private through their ancestor.
    """
    if isinstance(node, dict):
        for child_key, child in node.items():
            yield from _strings(child, (*path, child_key))
    elif isinstance(node, list):
        for child in node:
            yield from _strings(child, path)
    elif isinstance(node, str):
        yield path, node


def _is_placeholder(value: str) -> bool:
    return value.startswith("<") and value.endswith(">")


def test_no_artifact_leaks_real_library_content() -> None:
    """The corpus is public and permanent, so this must be able to fail.

    It replaces a denylist of strings the sanitizer already redacted
    unconditionally, which meant the assertion could never fire. It caught
    none of SortName, ForcedSortName, FileName, ServerName or the 97 raw
    external ids that the default-allow sanitizer published.
    """
    leaks: list[str] = []
    for artifact_path in sorted(ARTIFACT_ROOT.glob("*.json")):
        document = json.loads(artifact_path.read_text(encoding="utf-8"))
        for path, value in _strings(document):
            if _is_placeholder(value) or not value:
                continue
            # The manifest's own bookkeeping describes which upstream endpoint
            # was captured. Those are Emby's route names, not the operator's
            # content, and they have to stay readable for the corpus to be
            # auditable at all. Everything under request/ is still checked.
            if artifact_path.name == "manifest.json" and path[-1] in MANIFEST_BOOKKEEPING:
                continue
            where = ".".join(path)
            private_ancestor = any(
                part in component.casefold() for component in path for part in PRIVATE_ANCESTORS
            )
            if private_ancestor or (path and path[-1] in TITLE_KEYS):
                leaks.append(f"{artifact_path.name}: {where} = {value!r}")
            elif any(pattern.search(value) for pattern in LEAK_PATTERNS):
                leaks.append(f"{artifact_path.name}: {where} = {value!r} (matches a leak shape)")

    assert not leaks, "real library content in the public artifact corpus:\n" + "\n".join(
        sorted(set(leaks))[:40]
    )


def test_real_emby_artifacts_have_provenance_and_stable_sanitized_content() -> None:
    manifest_path = ARTIFACT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["emby_version"] == "4.9.5.0"
    assert manifest["sanitization"] == "shape-preserving-v2"
    assert {row["boundary"] for row in manifest["artifacts"]} >= REQUIRED_BOUNDARIES

    for row in manifest["artifacts"]:
        artifact_path = ARTIFACT_ROOT / row["file"]
        payload = artifact_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row["sanitized_sha256"]
        decoded = payload.decode("utf-8").lower()
        assert not any(marker in decoded for marker in PRIVATE_MARKERS)
        assert row["method"] in {"GET", "POST", "DELETE"}
        assert row["path"].startswith("/emby/")
        assert set(row["request"]) == {"query", "body"}
        assert row["raw_sha256"]

    errors = [row for row in manifest["artifacts"] if row["status"] >= 400]
    assert {row["boundary"] for row in errors} >= {"upstream-error"}
