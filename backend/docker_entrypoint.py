"""Initialize Docker's runtime config file before starting the application."""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _blank(stream: BinaryIO) -> bool:
    while chunk := stream.read(4096):
        if chunk.strip():
            return False
    return True


def _write_defaults(stream: BinaryIO) -> None:
    stream.seek(0)
    stream.write(b"{}\n")
    stream.truncate()
    stream.flush()
    with contextlib.suppress(OSError):
        os.fsync(stream.fileno())


def initialize_config(path: Path) -> bool:
    """Initialize only missing or blank files; preserve existing settings and inodes."""
    if path.exists() and not path.is_file():
        raise OSError(errno.EINVAL, "config.json must be a regular file, not a directory or device")
    try:
        with path.open("rb") as stream:
            if not _blank(stream):
                return False
    except FileNotFoundError:
        try:
            # Exclusive creation must never truncate a file another process created.
            with path.open("xb") as stream:
                _write_defaults(stream)
            return True
        except FileExistsError:
            with path.open("rb") as stream:
                if not _blank(stream):
                    return False

    # Write through the existing inode: replacing a single-file bind mount fails.
    with path.open("r+b") as stream:
        if not _blank(stream):
            return False
        _write_defaults(stream)
    return True


def main() -> int:
    try:
        initialized = initialize_config(CONFIG_PATH)
    except OSError as error:
        print(
            f"Cannot initialize runtime configuration at {CONFIG_PATH}: {error}. "
            "Create the host config.json as a writable regular file containing {} before "
            "starting Docker. Keep populated configuration files and existing appdata.",
            file=sys.stderr,
        )
        return 1
    if initialized:
        print(f"Initialized blank runtime configuration at {CONFIG_PATH} with {{}}.", flush=True)
    # Replace this process so container signals reach the usual application entrypoint.
    os.execv(  # noqa: S606 - fixed Python interpreter and application module, without a shell
        sys.executable, [sys.executable, "-m", "backend.app", *sys.argv[1:]]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
