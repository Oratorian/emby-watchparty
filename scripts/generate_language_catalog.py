"""Package the English UI catalog for runtime language-pack validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(root: Path = ROOT) -> str:
    source = root / "frontend" / "src" / "locales" / "en"
    namespaces = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(source.glob("*.json"))
    }
    if not namespaces:
        raise ValueError("No English translation catalogs found")
    return json.dumps({"format": 1, "messages": namespaces}, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "backend" / "language-catalog.json"
    expected = render()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            print("Generated language catalog is stale: backend/language-catalog.json")
            return 1
        return 0
    output.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
