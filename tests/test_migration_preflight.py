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


def test_proxied_deployment_requires_trusted_cidrs(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("BEHIND_PROXY=true\n", encoding="utf-8")

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert "REQUIRED ACTION: Set TRUSTED_PROXY_CIDRS" in output
    assert "TRUSTED_PROXY_CIDRS=172.16.0.0/12" in output


def test_development_reports_but_does_not_reject_disabled_hls(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"ENABLE_HLS_TOKEN_VALIDATION": false}', encoding="utf-8"
    )

    code, output = run_preflight(tmp_path, target="development", environ={})

    assert code == 0
    assert "ENABLE_HLS_TOKEN_VALIDATION=false (legacy config.json)" in output
    assert "REQUIRED ACTION: Set ENABLE_HLS_TOKEN_VALIDATION=true" not in output


def test_malformed_dotenv_fails_without_printing_its_contents(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET_SENTINEL_WITHOUT_EQUALS\n", encoding="utf-8")

    code, output = run_preflight(tmp_path, environ={})

    assert code == 1
    assert "ERROR: .env line 1 is malformed" in output
    assert "SECRET_SENTINEL" not in output


def test_non_file_legacy_config_is_an_inspection_error(tmp_path: Path) -> None:
    (tmp_path / "config.json").mkdir()

    code, output = run_preflight(tmp_path, environ={})

    assert code == 1
    assert "ERROR: config.json is not a regular file" in output


def test_inline_comments_are_read_the_way_the_application_reads_them(tmp_path: Path) -> None:
    """The preflight must resolve values through the loader the app uses.

    python-dotenv strips a trailing ` # comment`; a hand-rolled `split('=')`
    does not. The divergence broke both directions: correct settings were
    reported malformed, and `ENABLE_HLS_TOKEN_VALIDATION=false  # ...` parsed
    to None, which skipped the one required action a production upgrade of a
    2.x deployment with the HLS gate turned off actually depends on.
    """
    (tmp_path / ".env").write_text(
        "BEHIND_PROXY=true            # traefik in front\n"
        "TRUSTED_PROXY_CIDRS=172.16.0.0/12   # docker bridge\n"
        "SESSION_EXPIRY=1209600       # keep the 2.x 14-day cookie\n"
        "ENABLE_HLS_TOKEN_VALIDATION=false   # turned off in the 2.x admin panel\n",
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "BEHIND_PROXY=true (.env)" in output
    assert "SESSION_EXPIRY=1209600 (.env)" in output
    assert "ERROR: BEHIND_PROXY must be true or false" not in output
    assert "ERROR: SESSION_EXPIRY must be an integer number of seconds" not in output
    assert "ENABLE_HLS_TOKEN_VALIDATION=false (.env)" in output
    assert "REQUIRED ACTION: Set ENABLE_HLS_TOKEN_VALIDATION=true" in output


def test_unparseable_trusted_proxy_cidrs_is_reported_not_blessed(tmp_path: Path) -> None:
    """A non-empty CIDR list is not the same as a valid one.

    `Config.startup_errors` parses every entry with `ipaddress.ip_network` in
    every environment, so a space-separated list is one invalid token and 3.0
    serves the setup app on every route. Reporting `is declared` gave the
    operator positive evidence for the value that was about to stop the boot.
    """
    (tmp_path / ".env").write_text(
        "BEHIND_PROXY=true\nTRUSTED_PROXY_CIDRS=172.16.0.0/12 10.0.0.0/8\n",
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "TRUSTED_PROXY_CIDRS is declared" not in output
    assert "ERROR: TRUSTED_PROXY_CIDRS entry 1 is not a valid IP network" in output
    assert "REQUIRED ACTION: Set TRUSTED_PROXY_CIDRS to a comma-separated list" in output


def test_valid_comma_separated_cidrs_still_pass(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "BEHIND_PROXY=true\nTRUSTED_PROXY_CIDRS=172.16.0.0/12, 10.0.0.0/8\n",
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "TRUSTED_PROXY_CIDRS is declared (.env)" in output
    assert "is not a valid IP network" not in output


def test_production_boot_blockers_outside_the_boot_field_list_are_reported(
    tmp_path: Path,
) -> None:
    """The verdict comes from 3.0's boot gate, not from a hand-kept field list.

    A stock 2.1.x production .env carries wildcard CORS, a non-Secure cookie
    and no API key. Enumerating four boot fields by hand cleared it, and the
    upgrade then served 503 on every route.
    """
    (tmp_path / ".env").write_text(
        "APP_ENV=production\n"
        "BEHIND_PROXY=false\n"
        "CORS_ALLOWED_ORIGINS=*\n"
        "SESSION_COOKIE_SECURE=false\n"
        "SESSION_SECRET=SHORT_SENTINEL_SECRET\n",
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "REQUIRED ACTION: CORS_ALLOWED_ORIGINS must be explicit in production" in output
    assert "REQUIRED ACTION: SESSION_COOKIE_SECURE must be true in production" in output
    assert "REQUIRED ACTION: EMBY_API_KEY is required in production" in output
    assert "REQUIRED ACTION: SESSION_SECRET must be at least 32 characters in production" in output
    assert "SHORT_SENTINEL_SECRET" not in output


def test_a_valid_production_config_earns_an_explicit_all_clear(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_ENV=production\n"
        "BEHIND_PROXY=true\n"
        "TRUSTED_PROXY_CIDRS=172.16.0.0/12\n"
        f"SESSION_SECRET={'a' * 40}\n"
        "SESSION_COOKIE_SECURE=true\n"
        "CORS_ALLOWED_ORIGINS=https://watchparty.example.com\n"
        "EMBY_SERVER_URL=http://emby.example.com:8096\n"
        "EMBY_API_KEY=an-api-key\n",
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "INFO: 3.0 boot validation passes for target=production" in output
    assert "3.0 will not start otherwise" not in output


def test_development_target_is_not_judged_against_production_rules(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("BEHIND_PROXY=false\n", encoding="utf-8")

    code, output = run_preflight(tmp_path, target="development", environ={})

    assert code == 0
    assert "3.0 will not start otherwise" not in output
    assert "INFO: 3.0 boot validation passes for target=development" in output


def test_disabled_rate_limiting_is_not_reported_as_enforced(tmp_path: Path) -> None:
    """ENABLE_RATE_LIMITING is the master switch and it carries over verbatim.

    Reporting six limits as "enforced in 3.0" without reading it tells an
    operator who switched rate limiting off in the 2.1.x admin panel that they
    are protected while nothing is throttled.
    """
    (tmp_path / "config.json").write_text(
        '{"ENABLE_RATE_LIMITING": false, "RATE_LIMIT_CHAT": "4 per 3 seconds"}',
        encoding="utf-8",
    )

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert output.count("this limit is enforced in 3.0") == 0
    assert output.count("not enforced: ENABLE_RATE_LIMITING=false in config.json") == 6
    assert "REQUIRED ACTION: ENABLE_RATE_LIMITING=false carries into 3.0" in output


def test_enabled_rate_limiting_still_reports_every_limit_as_enforced(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"ENABLE_RATE_LIMITING": true}', encoding="utf-8")

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert output.count("this limit is enforced in 3.0") == 6
    assert "ENABLE_RATE_LIMITING=false carries into 3.0" not in output


def test_health_probe_urls_carry_the_application_prefix(tmp_path: Path) -> None:
    """Both probes are mounted under APP_PREFIX, so bare paths invert the signal.

    Against a healthy subpath deployment the unprefixed URL 404s, which reads
    as a failed upgrade; against a broken one it falls to the unprefixed 503
    catch-all and reports "dead" exactly where these lines promise to
    distinguish "misconfigured" from "dead".
    """
    (tmp_path / ".env").write_text("APP_PREFIX=/watchparty\n", encoding="utf-8")

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert "Healthy 3.0: /watchparty/api/health returns 200 ok" in output
    assert "/watchparty/api/ready returns 200" in output
    assert "Invalid production config: /watchparty/api/health returns 200 setup_required" in output


def test_health_probe_urls_drop_a_prefix_the_boot_gate_rejects(tmp_path: Path) -> None:
    """app.py serves unprefixed when APP_PREFIX fails validation; mirror that."""
    (tmp_path / ".env").write_text("APP_PREFIX=not-a-valid-prefix\n", encoding="utf-8")

    code, output = run_preflight(tmp_path, environ={})

    assert code == 0
    assert "Healthy 3.0: /api/health returns 200 ok" in output
    assert "not-a-valid-prefix/api/health" not in output


def test_json_null_legacy_hls_flag_reports_what_the_runtime_resolves(tmp_path: Path) -> None:
    """`legacy.get()` cannot tell an absent key from an explicit JSON null.

    RuntimeConfig coerces null to False, so reporting the default `true` put an
    INFO claiming the gate was on beside the action saying it must be turned on.
    """
    (tmp_path / "config.json").write_text(
        '{"ENABLE_HLS_TOKEN_VALIDATION": null}', encoding="utf-8"
    )

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 0
    assert "ENABLE_HLS_TOKEN_VALIDATION=false (legacy config.json)" in output
    assert "ENABLE_HLS_TOKEN_VALIDATION=true (default)" not in output
    assert "REQUIRED ACTION: Set ENABLE_HLS_TOKEN_VALIDATION=true" in output


def test_corrupt_legacy_config_is_never_side_moved_by_the_preflight(tmp_path: Path) -> None:
    """Read-only must hold on the failure path, not just the happy path.

    `RuntimeConfig.from_file` copies a corrupt config.json to
    `config.json.corrupt-<timestamp>`. Delegating the verdict to config.py
    must not drag that write in, so the runtime half is rebuilt from the JSON
    already parsed here instead.
    """
    (tmp_path / "config.json").write_text("{broken", encoding="utf-8")
    before = _fingerprint(tmp_path)

    code, output = run_preflight(tmp_path, target="production", environ={})

    assert code == 1
    assert "ERROR: config.json is not valid JSON" in output
    assert _fingerprint(tmp_path) == before
    assert list(tmp_path.glob("config.json.corrupt-*")) == []
