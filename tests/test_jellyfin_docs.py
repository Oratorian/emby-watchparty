import re
from pathlib import Path

from backend.src.config import _RETIRED_PROVIDER_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def _prose(*paths: str) -> str:
    """Join the documents with runs of whitespace flattened to single spaces.

    These are hand-wrapped markdown, so a sentence this guard looks for
    routinely straddles a line break. Matching the raw text made the guard
    fire on a reflow, which says nothing about whether the operator was told
    the thing.
    """
    return re.sub(
        r"\s+",
        " ",
        "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths),
    )


def test_operator_docs_cover_jellyfin_selection_and_hls_limits() -> None:
    combined = _prose("README.md", "docs/deployment/compose.md")

    # The type is the whole of the provider selection now: one address and one
    # key serve both, and nothing auto-detects which server answers them. An
    # operator who reads only about the URL and the key has not been told the
    # one thing they still have to state.
    assert "MEDIA_SERVER_TYPE=jellyfin" in combined
    assert "MEDIA_SERVER_URL" in combined
    assert "MEDIA_SERVER_API_KEY" in combined
    assert "Changing providers requires a restart" in combined
    assert "HLS-only" in combined
    assert "Live TV" in combined
    assert "SyncPlay" in combined


def test_the_migration_doc_maps_every_retired_name_to_its_replacement() -> None:
    """The retired names have no alias, so the doc is the only recovery path.

    Setting one is a boot error naming its replacement, which covers the
    operator who reads logs. The one who reads the release notes first needs
    the same mapping written down, and there is nothing in the running system
    left to infer it from.
    """
    migration = _prose("docs/Migration-HowTo.md")

    for retired, replacement in _RETIRED_PROVIDER_FIELDS.items():
        assert retired in migration, f"{retired} was retired without an upgrade note"
        assert replacement in migration
