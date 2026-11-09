"""Execute the generated host-setup instructions against disposable files."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.generate_deployment_artifacts import generate_artifacts, load_schema


@pytest.fixture(scope="module")
def bash_executable() -> str:
    executable = shutil.which("bash")
    if executable:
        return executable
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    pytest.skip("Bash is not installed; cannot execute the generated POSIX setup instructions.")


def _generated_config_setup() -> str:
    compose = generate_artifacts(load_schema())[Path("docker-compose.yml.example")]
    lines = compose.splitlines()
    start = next(
        index for index, line in enumerate(lines) if re.match(r"#   if\b.*config\.json", line)
    )
    commands: list[str] = []
    for line in lines[start:]:
        if not line.startswith("#   "):
            break
        commands.append(line[4:])
    assert commands[-1].strip() == "fi"
    return "\n".join(commands) + "\n"


@pytest.mark.parametrize("state", ["missing", "empty", "valid", "malformed", "directory"])
def test_generated_setup_initializes_only_missing_or_empty_host_files(
    tmp_path: Path, bash_executable: str, state: str
) -> None:
    path = tmp_path / "config.json"
    originals = {
        "empty": b"",
        "valid": b'{\n  "REQUIRE_LOGIN": true, "MAX_USERS": 27\n}\n',
        "malformed": b'{"MAX_USERS":\n',
    }
    if state == "directory":
        path.mkdir()
        (path / "keep.txt").write_bytes(b"existing appdata must survive\n")
    elif state != "missing":
        path.write_bytes(originals[state])

    # The code is taken verbatim from the generated Compose comments, and runs
    # only in this synthetic directory with user shell startup files disabled.
    environment = os.environ.copy()
    environment.pop("BASH_ENV", None)
    environment.pop("ENV", None)
    result = subprocess.run(  # noqa: S603 - exercising repository-generated setup instructions
        [bash_executable, "--noprofile", "--norc", "-c", _generated_config_setup()],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if state == "directory":
        assert result.returncode != 0
        assert "config.json" in result.stderr
        assert "file" in result.stderr
        assert path.is_dir()
        assert (path / "keep.txt").read_bytes() == b"existing appdata must survive\n"
    else:
        assert result.returncode == 0, result.stderr
        if state in {"missing", "empty"}:
            payload = path.read_bytes()
            assert payload == b"{}\n"
            assert json.loads(payload) == {}
        else:
            assert path.read_bytes() == originals[state]
