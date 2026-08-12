"""Validate ownership and expiry metadata for Trivy exceptions."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

import yaml

STATEMENT = re.compile(r"^owner=\S+; reason=\S.+$")


def _future_date(value: object) -> bool:
    if isinstance(value, dt.datetime):
        parsed = value.date()
    elif isinstance(value, dt.date):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = dt.date.fromisoformat(value)
        except ValueError:
            return False
    else:
        return False
    return parsed > dt.datetime.now(dt.UTC).date()


def _errors(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return ["ignore policy must be a YAML object"]
    errors: list[str] = []
    for section in ("vulnerabilities", "misconfigurations"):
        entries = document.get(section, [])
        if not isinstance(entries, list):
            errors.append(f"{section} must be a list")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{section}[{index}] must be an object")
                continue
            identifier = entry.get("id") or f"{section}[{index}]"
            if not _future_date(entry.get("expired_at")):
                errors.append(f"{identifier}: expired_at must be a future ISO date")
            statement = entry.get("statement")
            if not isinstance(statement, str) or STATEMENT.fullmatch(statement) is None:
                errors.append(
                    f"{identifier}: statement must be 'owner=<login>; reason=<risk acceptance>'"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path(".trivyignore.yaml"))
    args = parser.parse_args(argv)
    document = yaml.safe_load(args.file.read_text(encoding="utf-8"))
    errors = _errors(document)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"{args.file}: exception policy valid")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
