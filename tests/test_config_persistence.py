"""Regression guard: saving must work when config.json is a bind mount.

`RuntimeConfig.save()` wrote a sibling temp file and renamed it onto the
target. A single-file bind mount, the layout both the README and
docker-compose.yml.example recommend, makes that target a mount point, and
rename(2) onto a mount point fails with EBUSY. Every save from /admin was
rejected with "[Errno 16] Device or resource busy", the host file never
changed, and an orphaned config.json.*.tmp was left behind on each attempt.

A real bind mount needs root and a Linux kernel, so these tests reproduce the
only thing save() can actually observe about one: the errno rename(2) returns.

Reported as #66 against 2.1.2, and present here unchanged.
"""

import errno
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.src.config import RuntimeConfig


def _refuse(err: int) -> Callable[..., None]:
    """Stand in for the kernel refusing to rename onto a mount point."""

    def raiser(*_args: object, **_kwargs: object) -> None:
        raise OSError(err, os.strerror(err))

    return raiser


@pytest.fixture
def target(tmp_path: Path) -> Path:
    # The bind-mounted file always exists already: `touch config.json` on the
    # host is step one of the documented setup.
    path = tmp_path / "config.json"
    path.write_text("{}\n", encoding="utf-8")
    return path


def _leftover_temp_files(target: Path) -> list[str]:
    return sorted(p.name for p in target.parent.glob("config.json.*.tmp"))


def test_settings_are_written_through_when_rename_is_refused(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = RuntimeConfig()
    config.REQUIRE_LOGIN = not config.REQUIRE_LOGIN
    monkeypatch.setattr(os, "replace", _refuse(errno.EBUSY))

    config.save(target)

    assert json.loads(target.read_text(encoding="utf-8")) == config.to_dict()


def test_the_host_inode_survives(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserving it is the entire reason the mount exists.

    A save that swaps the inode writes into a file the host no longer sees, so
    the setting appears to stick until the container is recreated.
    """
    before = target.stat().st_ino
    monkeypatch.setattr(os, "replace", _refuse(errno.EBUSY))

    RuntimeConfig().save(target)

    assert target.stat().st_ino == before


def test_no_temp_file_is_orphaned(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "replace", _refuse(errno.EBUSY))

    RuntimeConfig().save(target)

    assert _leftover_temp_files(target) == []


def test_a_longer_previous_config_does_not_leave_a_trailing_tail(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without truncate() the old tail survives past the new payload.

    The result parses as neither JSON nor defaults, so from_file() would fall
    back to defaults and silently discard every tuned setting.
    """
    target.write_text(json.dumps({"PAD": "x" * 10000}), encoding="utf-8")
    monkeypatch.setattr(os, "replace", _refuse(errno.EBUSY))

    RuntimeConfig().save(target)

    assert json.loads(target.read_text(encoding="utf-8")) == RuntimeConfig().to_dict()


def test_a_cross_device_target_takes_the_same_path(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", _refuse(errno.EXDEV))

    RuntimeConfig().save(target)

    assert json.loads(target.read_text(encoding="utf-8")) == RuntimeConfig().to_dict()


def test_a_normal_file_is_still_replaced_atomically(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bind-mount recovery must not cost everyone else atomicity."""
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src: object, dst: object, *args: object, **kwargs: object) -> None:
        calls.append((str(src), str(dst)))
        real_replace(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", spy)

    RuntimeConfig().save(target)

    assert len(calls) == 1
    assert calls[0][0].endswith(".tmp")
    assert calls[0][1] == str(target)
    assert json.loads(target.read_text(encoding="utf-8")) == RuntimeConfig().to_dict()
    assert _leftover_temp_files(target) == []


def test_save_creates_the_file_when_it_does_not_exist_yet(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.json"

    RuntimeConfig().save(fresh)

    assert json.loads(fresh.read_text(encoding="utf-8")) == RuntimeConfig().to_dict()


def test_an_unrelated_rename_error_is_not_swallowed(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only EBUSY and EXDEV mean "this target cannot be renamed onto".

    A permissions problem is a real failure and must still surface, or a
    read-only mount would report every save as successful.
    """
    monkeypatch.setattr(os, "replace", _refuse(errno.EACCES))

    # EACCES constructs a PermissionError, so the narrower class is also the
    # accurate one here; the errno assertion is what pins the intent.
    with pytest.raises(PermissionError) as caught:
        RuntimeConfig().save(target)

    assert caught.value.errno == errno.EACCES


def test_a_failed_save_still_cleans_up_after_itself(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported symptom was a new config.json.*.tmp on every attempt."""
    monkeypatch.setattr(os, "replace", _refuse(errno.EACCES))

    with pytest.raises(PermissionError):
        RuntimeConfig().save(target)

    assert _leftover_temp_files(target) == []
