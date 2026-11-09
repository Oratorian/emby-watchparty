"""Docker startup initializes empty bind-mounted configs without replacing files."""

import errno
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from backend import docker_entrypoint

ROOT = Path(__file__).resolve().parents[1]


def test_missing_config_is_created_as_an_empty_json_object(tmp_path: Path) -> None:
    path = tmp_path / "config.json"

    assert docker_entrypoint.initialize_config(path) is True
    assert path.read_bytes() == b"{}\n"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("contents", [b"", b" ", b"\t\r\n \v\f", b" " * 8193])
def test_blank_config_is_initialized_in_place(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(contents)
    path.chmod(0o600)
    before = path.stat()

    assert docker_entrypoint.initialize_config(path) is True

    after = path.stat()
    assert path.read_bytes() == b"{}\n"
    assert after.st_ino == before.st_ino
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "contents",
    [
        b"{}\n",
        b'{"REQUIRE_LOGIN":true,"MAX_USERS":8}\n',
        b" {broken",
        b"null",
        b"[]",
        b"\xef\xbb\xbf{}\n",
        b"\x00",
        b" \xc2\xa0 ",
        b" " * 8192 + b'{"MAX_USERS":9}',
    ],
)
def test_nonblank_configs_are_never_rewritten(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(contents)
    before = path.stat()

    assert docker_entrypoint.initialize_config(path) is False

    after = path.stat()
    assert path.read_bytes() == contents
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns
    assert list(tmp_path.iterdir()) == [path]


def test_populated_readonly_config_does_not_need_write_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    contents = b'{"REQUIRE_LOGIN":true}\n'
    path.write_bytes(contents)
    real_open = Path.open
    writable_opens: list[str] = []

    def protected_open(target: Path, mode: str = "r", *args, **kwargs):
        if target == path and any(flag in mode for flag in "wax+"):
            writable_opens.append(mode)
            raise PermissionError(errno.EACCES, "read-only test config")
        return real_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", protected_open)

    assert docker_entrypoint.initialize_config(path) is False
    assert writable_opens == []
    assert path.read_bytes() == contents


@pytest.mark.parametrize("failure", [errno.EACCES, errno.EROFS])
def test_blank_readonly_config_fails_instead_of_claiming_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int
) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"")
    real_open = Path.open

    def readonly_open(target: Path, mode: str = "r", *args, **kwargs):
        if target == path and any(flag in mode for flag in "wax+"):
            raise OSError(failure, "read-only test config")
        return real_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", readonly_open)

    with pytest.raises(OSError, match="read-only test config") as caught:
        docker_entrypoint.initialize_config(path)
    assert caught.value.errno == failure
    assert path.read_bytes() == b""


def test_unreadable_config_fails_without_overwriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b'{"REQUIRE_LOGIN":true}')
    real_open = Path.open

    def unreadable_open(target: Path, *args, **kwargs):
        if target == path:
            raise PermissionError(errno.EACCES, "unreadable test config")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unreadable_open)

    with pytest.raises(PermissionError):
        docker_entrypoint.initialize_config(path)
    with real_open(path, "rb") as stream:
        assert stream.read() == b'{"REQUIRE_LOGIN":true}'


def test_directory_mount_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.mkdir()
    marker = path / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(OSError, match="regular file"):
        docker_entrypoint.initialize_config(path)
    assert path.is_dir()
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_nonregular_mount_is_rejected_before_opening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"")
    real_stat = Path.stat
    real_open = Path.open

    def fifo_stat(target: Path, *args, **kwargs):
        info = real_stat(target, *args, **kwargs)
        if target == path:
            values = list(info)
            values[0] = stat.S_IFIFO | 0o600
            return os.stat_result(values)
        return info

    def no_fifo_open(target: Path, *args, **kwargs):
        if target == path:
            pytest.fail("A nonregular configuration file must not be opened.")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fifo_stat)
    monkeypatch.setattr(Path, "open", no_fifo_open)

    with pytest.raises(OSError, match="regular file"):
        docker_entrypoint.initialize_config(path)


def test_a_concurrent_creator_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    contents = b'{"MAX_USERS":23}\n'
    real_open = Path.open
    created_by_other = False

    def racing_open(target: Path, mode: str = "r", *args, **kwargs):
        nonlocal created_by_other
        if target == path and "x" in mode and not created_by_other:
            with real_open(path, "wb") as stream:
                stream.write(contents)
            created_by_other = True
        return real_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)

    assert docker_entrypoint.initialize_config(path) is False
    assert created_by_other
    assert path.read_bytes() == contents


def test_content_written_between_read_and_writable_open_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"")
    contents = b'{"MAX_USERS":42}\n'
    real_open = Path.open
    changed_by_other = False

    def racing_open(target: Path, mode: str = "r", *args, **kwargs):
        nonlocal changed_by_other
        if target == path and "+" in mode and not changed_by_other:
            with real_open(path, "wb") as stream:
                stream.write(contents)
            changed_by_other = True
        return real_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)

    assert docker_entrypoint.initialize_config(path) is False
    assert changed_by_other
    assert path.read_bytes() == contents


def test_main_initializes_then_replaces_itself_with_the_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setattr(docker_entrypoint, "CONFIG_PATH", path)
    monkeypatch.setattr(sys, "argv", ["backend.docker_entrypoint", "--example", "value"])

    class AppExecutedError(Exception):
        pass

    def exec_app(program: str, arguments: list[str]) -> None:
        assert path.read_bytes() == b"{}\n"
        assert program == sys.executable
        assert arguments == [sys.executable, "-m", "backend.app", "--example", "value"]
        raise AppExecutedError

    monkeypatch.setattr(docker_entrypoint.os, "execv", exec_app)

    with pytest.raises(AppExecutedError):
        docker_entrypoint.main()


def test_main_reports_an_actionable_error_without_starting_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.json"
    path.mkdir()
    monkeypatch.setattr(docker_entrypoint, "CONFIG_PATH", path)
    calls: list[object] = []
    monkeypatch.setattr(docker_entrypoint.os, "execv", lambda *args: calls.append(args))

    assert docker_entrypoint.main() == 1
    assert calls == []
    message = capsys.readouterr().err.lower()
    assert "config.json" in message
    assert "file" in message
    assert "mount" in message or "directory" in message


def test_docker_bootstrap_is_a_default_command_not_a_forced_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["python", "-m", "backend.docker_entrypoint"]' in dockerfile
    assert not re.search(r"^\s*ENTRYPOINT\b", dockerfile, flags=re.MULTILINE)
    assert "python -m backend.app" not in dockerfile.split("CMD [", 1)[-1]
