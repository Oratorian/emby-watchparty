"""The runtime catalog must follow the frontend without requiring its source at runtime."""

import json
from pathlib import Path

from scripts.generate_language_catalog import ROOT, render


def test_packaged_language_catalog_matches_frontend() -> None:
    assert (ROOT / "backend" / "language-catalog.json").read_text(encoding="utf-8") == render()


def test_generator_discovers_namespaces_and_preserves_interpolation(tmp_path: Path) -> None:
    source = tmp_path / "frontend" / "src" / "locales" / "en"
    source.mkdir(parents=True)
    (source / "extra.json").write_text('{"message": "Welcome, {name}"}', encoding="utf-8")
    result = json.loads(render(tmp_path))
    assert result == {"format": 1, "messages": {"extra": {"message": "Welcome, {name}"}}}
