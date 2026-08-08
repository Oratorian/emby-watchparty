import hashlib
from pathlib import Path

from backend.migration_preflight import run_preflight


def _fingerprint(root: Path) -> dict[str, tuple[str, int]]:
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preflight_reports_precedence_rates_and_never_writes_or_prints_secrets(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "BEHIND_PROXY=true\n"
        "TRUSTED_PROXY_CIDRS=172.16.0.0/12\n"
        "ENABLE_HLS_TOKEN_VALIDATION=false\n"
        "SESSION_SECRET=DOTENV_SENTINEL_SECRET\n"
        "EMBY_API_KEY=DOTENV_SENTINEL_KEY\n",
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        '{"ENABLE_HLS_TOKEN_VALIDATION": false,"UNKNOWN_TOKEN": "CONFIG_SENTINEL_TOKEN"}',
        encoding="utf-8",
    )
    before = _fingerprint(tmp_path)

    code, output = run_preflight(
        tmp_path,
        target="production",
        deployment="docker",
        environ={"ENABLE_HLS_TOKEN_VALIDATION": "true", "SESSION_SECRET": "PROCESS_SECRET"},
    )

    assert code == 0
    assert "ENABLE_HLS_TOKEN_VALIDATION=true (process environment)" in output
    assert "BEHIND_PROXY=true (.env)" in output
    assert "DOTENV_SENTINEL" not in output
    assert "PROCESS_SECRET" not in output
    assert "CONFIG_SENTINEL" not in output
    assert _fingerprint(tmp_path) == before


def test_preflight_names_production_actions_for_disabled_legacy_hls_and_proxy(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text(
        '{"ENABLE_HLS_TOKEN_VALIDATION": false}', encoding="utf-8"
    )

    code, output = run_preflight(
        tmp_path,
        target="production",
        deployment="docker",
        environ={},
    )

    assert code == 0
    assert "REQUIRED ACTION: Set BEHIND_PROXY=true or BEHIND_PROXY=false" in output
    assert "ENABLE_HLS_TOKEN_VALIDATION=false (legacy config.json)" in output
    assert "REQUIRED ACTION: Set ENABLE_HLS_TOKEN_VALIDATION=true" in output
    assert "SESSION_EXPIRY=1209600" in output


def test_preflight_accepts_direct_deployment_and_reports_default_hls(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("BEHIND_PROXY=false\nTRUSTED_PROXY_CIDRS=\n", encoding="utf-8")

    code, output = run_preflight(
        tmp_path,
        target="production",
        deployment="docker",
        environ={},
    )

    assert code == 0
    assert "BEHIND_PROXY=false (.env)" in output
    assert "ENABLE_HLS_TOKEN_VALIDATION=true (default)" in output
    assert "REQUIRED ACTION: Set TRUSTED_PROXY_CIDRS" not in output


def test_preflight_fails_only_when_input_cannot_be_inspected(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{broken", encoding="utf-8")

    code, output = run_preflight(
        tmp_path,
        target="development",
        deployment="docker",
        environ={},
    )

    assert code == 1
    assert "ERROR: config.json is not valid JSON" in output


def test_preflight_reports_each_effective_legacy_rate_limit(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"RATE_LIMIT_API_CALLS": "77 per minute","RATE_LIMIT_CHAT": "4 per 3 seconds"}',
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert "RATE_LIMIT_API_CALLS=77 per minute (legacy config.json)" in output
    assert "RATE_LIMIT_CHAT=4 per 3 seconds (legacy config.json)" in output
    assert "RATE_LIMIT_LOGIN=10 per 15 minutes (default)" in output
    assert output.count("this limit is enforced in 3.0") == 6


def test_preflight_reports_malformed_rate_without_echoing_value(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"RATE_LIMIT_LOGIN": "SECRET_SENTINEL"}', encoding="utf-8"
    )

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert "ERROR: RATE_LIMIT_LOGIN has a malformed legacy value" in output
    assert "SECRET_SENTINEL" not in output


def test_source_and_windows_requirements_are_explicit(tmp_path: Path) -> None:
    code, output = run_preflight(
        tmp_path,
        target="development",
        deployment="source",
        environ={"WEB_CONCURRENCY": "2"},
        platform_name="win32",
        python_version=(3, 13, 0),
        node_version=(20, 18, 0),
    )

    assert code == 0
    assert "REQUIRED ACTION: Use Python >=3.12,<3.13" in output
    assert "REQUIRED ACTION: Use Node >=20.19" in output
    assert "REQUIRED ACTION: Run exactly one application worker" in output
    assert "INFO: Windows support is best effort; Docker/Linux is recommended" in output


def test_source_runtime_versions_and_single_worker_can_pass(tmp_path: Path) -> None:
    code, output = run_preflight(
        tmp_path,
        target="development",
        deployment="source",
        environ={"UVICORN_WORKERS": "1"},
        platform_name="linux",
        python_version=(3, 12, 9),
        node_version=(24, 1, 0),
    )

    assert code == 0
    assert "Python 3.12.9 meets >=3.12,<3.13" in output
    assert "Node 24.1.0 meets >=20.19" in output
    assert "Application worker count is 1" in output
