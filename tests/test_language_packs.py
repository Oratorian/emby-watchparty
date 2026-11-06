from __future__ import annotations

import asyncio
import io
import json
import stat
import struct
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.language_packs import (
    MAX_EXPANDED_BYTES,
    MAX_UPLOAD_BYTES,
    LanguagePackError,
    LanguagePackStore,
)
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET


def _archive(
    messages: dict | None = None,
    *,
    locale: str = "fr",
    extra: list[tuple[str | zipfile.ZipInfo, str | bytes]] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": 1, "locale": locale, "name": "Français"})
        )
        for namespace, value in (messages or {"core": {"language": "Langue"}}).items():
            archive.writestr(f"{namespace}.json", json.dumps(value))
        for name, value in extra or []:
            archive.writestr(name, value)
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path: Path) -> LanguagePackStore:
    catalog = tmp_path / "english.json"
    catalog.write_text(
        json.dumps(
            {
                "format": 1,
                "messages": {
                    "core": {
                        "language": "Language",
                        "greeting": "Hello {name}",
                        "plural": "{count} viewer | {count} viewers",
                        "email": "you{'@'}example.com",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return LanguagePackStore(tmp_path / "data" / "languages", catalog_path=catalog)


def test_partial_pack_persists_and_reloads_without_frontend_sources(store: LanguagePackStore):
    pack = store.install(_archive())
    assert pack.summary() == {
        "locale": "fr",
        "name": "Français",
        "author": "",
        "version": "",
        "revision": pack.revision,
    }
    assert len(pack.revision) == 64
    restarted = LanguagePackStore(store.directory, catalog_path=store.catalog_path)
    assert restarted.list()[0].payload() == pack.payload()
    assert restarted.delete("fr")
    assert restarted.get("fr") is None


def test_valid_named_literal_and_plural_messages(store: LanguagePackStore):
    pack = store.install(
        _archive(
            {
                "core": {
                    "greeting": "Bonjour {name}",
                    "plural": "{count} personne | {count} personnes",
                    "email": "vous{'@'}exemple.fr",
                }
            }
        )
    )
    assert pack.messages["core"] == {
        "greeting": "Bonjour {name}",
        "plural": "{count} personne | {count} personnes",
        "email": "vous{'@'}exemple.fr",
    }


@pytest.mark.parametrize(
    "messages",
    [
        {"core": {"greeting": "Bonjour"}},
        {"core": {"greeting": "Bonjour {username}"}},
        {"core": {"language": "<img src=x>"}},
        {"core": {"language": "@:core.language"}},
        {"core": {"language": "{bad"}},
        {"core": {"language": "yes | "}},
        {"core": {"language": ""}},
        {"core": {"unknown": "Bonjour"}},
        {"core": {"language": ["Bonjour"]}},
        {"core": {"language.child": "Bonjour"}},
        {"core": {"language": "Langue", "unknown": {}}},
        {"core": {"language": {}, "greeting": "Bonjour {name}"}},
        {"core": {"__proto__": "Bonjour"}},
        {"unknown": {"language": "Bonjour"}},
    ],
)
def test_invalid_messages_do_not_replace_existing_pack(store: LanguagePackStore, messages: dict):
    original = store.install(_archive())
    with pytest.raises(LanguagePackError):
        store.install(_archive(messages))
    assert store.get("fr").revision == original.revision


@pytest.mark.parametrize("message", [r"{'\q'}", r"{'\uZZZZ'}", r"{'a\nb'}", "{'a\nb'}", r"{'\'}"])
def test_invalid_quoted_literal_escapes_rejected(store: LanguagePackStore, message: str):
    with pytest.raises(LanguagePackError, match="Quoted literals"):
        store.install(_archive({"core": {"language": message}}))


def test_backslashes_outside_literals_remain_plain_text(store: LanguagePackStore):
    message = r"Dossier C:\media"
    pack = store.install(_archive({"core": {"language": message}}))
    assert pack.messages["core"] == {"language": message}


@pytest.mark.parametrize("locale", ["en", "EN", "auto", "../fr", "fr/FR", "fr_FR", "fr-FR/../../x"])
@pytest.mark.parametrize("operation", ["install", "get", "delete"])
def test_reserved_or_unsafe_locales_rejected(store: LanguagePackStore, locale: str, operation: str):
    argument = _archive(locale=locale) if operation == "install" else locale
    with pytest.raises(LanguagePackError):
        getattr(store, operation)(argument)
    assert not store.directory.exists()


@pytest.mark.parametrize("operation", ["install", "get", "delete"])
@pytest.mark.parametrize("target_location", ["inside", "sibling"])
def test_pack_file_symlinks_cannot_read_replace_or_delete_another_file(
    store: LanguagePackStore, operation: str, target_location: str
):
    store.install(_archive(locale="de"))
    original = (store.directory / "pack-de.json").read_bytes()
    if target_location == "inside":
        target = store.directory / "pack-de.json"
    else:
        sibling = store.directory.with_name("languages-backup")
        sibling.mkdir()
        target = sibling / "pack-fr.json"
        target.write_bytes(original)
    link = store.directory / "pack-fr.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("File symlinks are not available to this test process.")
    argument = _archive() if operation == "install" else "fr"
    with pytest.raises(LanguagePackError, match="language directory"):
        getattr(store, operation)(argument)
    assert target.read_bytes() == original
    assert link.is_symlink()
    assert [pack.manifest["locale"] for pack in store.list()] == ["de"]


def test_canonical_locale_and_german_override(store: LanguagePackStore):
    assert store.install(_archive(locale="pt-br")).manifest["locale"] == "pt-BR"
    assert store.get("PT-br").manifest["locale"] == "pt-BR"
    assert store.install(_archive(locale="de")).manifest["locale"] == "de"


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("IW", "iw"),
        ("zh-hant-tw", "zh-Hant-TW"),
        ("en-us-FONIPA", "en-US-fonipa"),
        ("de-1901", "de-1901"),
    ],
)
def test_locale_alias_identity_and_subtag_case(
    store: LanguagePackStore, locale: str, expected: str
):
    assert store.install(_archive(locale=locale)).manifest["locale"] == expected


@pytest.mark.parametrize("locale", ["con", "aux", "prn", "nul"])
def test_windows_device_names_use_safe_file_prefix(store: LanguagePackStore, locale: str):
    installed = store.install(_archive(locale=locale))
    assert (store.directory / f"pack-{locale}.json").is_file()
    assert store.get(locale).revision == installed.revision
    assert store.list()[0].manifest["locale"] == locale
    assert store.delete(locale)


@pytest.mark.parametrize(
    "messages",
    [
        {"core": {"language": "\ud800"}},
        {"core": {"\ud800": "Bonjour"}},
    ],
)
def test_lone_surrogates_in_messages_or_keys_are_rejected(store: LanguagePackStore, messages: dict):
    with pytest.raises(LanguagePackError, match="UTF-8"):
        store.install(_archive(messages))


def test_lone_surrogate_in_manifest_is_rejected(store: LanguagePackStore):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", b'{"format":1,"locale":"fr","name":"\\ud800"}')
        archive.writestr("core.json", '{"language":"Bonjour"}')
    with pytest.raises(LanguagePackError, match="UTF-8"):
        store.install(buffer.getvalue())


def test_corrupt_deflate_stream_returns_validation_error(store: LanguagePackStore):
    raw = bytearray(_archive())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = archive.getinfo("core.json")
    name_length, extra_length = struct.unpack_from("<HH", raw, entry.header_offset + 26)
    offset = entry.header_offset + 30 + name_length + extra_length
    raw[offset] = 7  # Reserved deflate block type.
    with pytest.raises(LanguagePackError, match="ZIP"):
        store.install(bytes(raw))


@pytest.mark.parametrize(
    "filename",
    ["../core.json", "/core.json", "fr/core.json", "core.json\\x", "readme.exe", "CORE.json"],
)
def test_unexpected_or_traversing_archive_names_rejected(store: LanguagePackStore, filename: str):
    with pytest.raises(LanguagePackError):
        store.install(_archive(extra=[(filename, "{}")]))
    assert not store.directory.exists()


def test_symlinks_and_duplicate_zip_entries_rejected(store: LanguagePackStore):
    symlink = zipfile.ZipInfo("core.json")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", '{"format":1,"locale":"fr","name":"Français"}')
        archive.writestr(symlink, "../../victim")
    with pytest.raises(LanguagePackError):
        store.install(buffer.getvalue())
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = _archive(extra=[("core.json", "{}")])
    with pytest.raises(LanguagePackError):
        store.install(duplicate)


def test_corrupt_oversized_and_expanding_archives_rejected(store: LanguagePackStore):
    for raw in [b"not a ZIP", b"x" * (MAX_UPLOAD_BYTES + 1)]:
        with pytest.raises(LanguagePackError):
            store.install(raw)
    with pytest.raises(LanguagePackError):
        store.install(_archive({"core": {"language": "x" * (MAX_EXPANDED_BYTES + 1)}}))


def test_duplicate_json_keys_rejected(store: LanguagePackStore):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", '{"format":1,"locale":"fr","name":"French"}')
        archive.writestr("core.json", '{"language":"Bonjour","language":"Salut"}')
    with pytest.raises(LanguagePackError, match="Duplicate JSON"):
        store.install(buffer.getvalue())


def test_failed_atomic_replace_preserves_previous_file(store: LanguagePackStore, monkeypatch):
    original = store.install(_archive())
    original_bytes = (store.directory / "pack-fr.json").read_bytes()

    def fail_replace(_source, _target):
        raise OSError("read-only volume")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="read-only"):
        store.install(_archive({"core": {"language": "Nouvelle langue"}}))
    assert (store.directory / "pack-fr.json").read_bytes() == original_bytes
    assert store.get("fr").revision == original.revision
    assert not list(store.directory.glob(".language-*"))


def test_corrupt_persisted_pack_is_not_publicly_listed(store: LanguagePackStore):
    store.install(_archive())
    (store.directory / "pack-fr.json").write_text("not JSON", encoding="utf-8")
    assert store.list() == []


def test_template_has_all_namespaces_and_can_be_imported(store: LanguagePackStore):
    raw = store.template()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "core.json"}
    assert store.install(raw).manifest["locale"] == "fr"


def _application(tmp_path: Path, prefix: str = ""):
    upstream = FastAPI()

    @upstream.post("/emby/Users/AuthenticateByName")
    async def authenticate():
        return {
            "AccessToken": "synthetic-token",
            "User": {"Id": "admin", "Name": "Alice", "Policy": {"IsAdministrator": True}},
        }

    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            TRUSTED_PROXY_CIDRS=(),
            APP_ENV="development",
            APP_PREFIX=prefix,
            MEDIA_SERVER_URL="http://emby.test",
            MEDIA_SERVER_API_KEY="synthetic-key",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    return create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=upstream),
    )


@pytest.mark.parametrize("prefix", ["", "/watchparty"])
def test_protected_upload_public_catalog_restart_and_delete(tmp_path: Path, prefix: str):
    async def exercise():
        async with asgi_client(_application(tmp_path, prefix)) as client:
            public = f"{prefix}/api/languages"
            admin = f"{prefix}/api/admin/languages"
            assert (await client.get(public)).json() == {"languages": []}
            assert (
                await client.post(admin, files={"file": ("fr.zip", _archive())})
            ).status_code == 401
            assert (await client.get(f"{admin}/template")).status_code == 401
            assert (await client.delete(f"{admin}/fr")).status_code == 401
            assert not (tmp_path / "data" / "languages").exists()
            login = await client.post(
                f"{prefix}/api/admin/login", json={"username": "Alice", "password": "test"}
            )
            assert login.json()["success"]
            template = await client.get(f"{admin}/template")
            assert template.headers["content-type"] == "application/zip"
            assert "manifest.json" in zipfile.ZipFile(io.BytesIO(template.content)).namelist()
            uploaded = await client.post(
                admin, files={"file": ("fr.zip", _archive(), "application/zip")}
            )
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()["author"] == ""
            listed = await client.get(public)
            assert listed.json()["languages"][0] == uploaded.json()
            assert listed.headers["cache-control"] == "no-store"
            messages = await client.get(f"{public}/fr")
            assert messages.json()["messages"] == {"core": {"language": "Langue"}}
            assert messages.headers["cache-control"] == "no-store"
            invalid = await client.post(admin, files={"file": ("bad.zip", b"not ZIP")})
            assert invalid.status_code == 400
            assert invalid.json()["code"] == "invalid_language_pack"
        async with asgi_client(_application(tmp_path, prefix)) as client:
            assert (await client.get(f"{public}/fr")).json()["messages"] == {
                "core": {"language": "Langue"}
            }
            await client.post(
                f"{prefix}/api/admin/login", json={"username": "Alice", "password": "test"}
            )
            assert (await client.delete(f"{admin}/fr")).json()["success"]
            assert (await client.get(f"{public}/fr")).status_code == 404

    asyncio.run(exercise())


def test_unauthenticated_upload_does_not_read_body(tmp_path: Path):
    async def exercise():
        consumed = False

        async def body():
            nonlocal consumed
            consumed = True
            yield b"x" * (MAX_UPLOAD_BYTES * 2)

        async with asgi_client(_application(tmp_path)) as client:
            response = await client.post("/api/admin/languages", content=body())
            assert response.status_code == 401
            assert not consumed

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["multipart", "validation"])
def test_upload_errors_only_return_curated_client_details(
    tmp_path: Path, monkeypatch, failure: str
):
    private_detail = "internal parser failure at /private/watchparty/config.json"

    if failure == "multipart":

        async def reject_multipart(_request):
            raise StarletteHTTPException(status_code=400, detail=private_detail)

        monkeypatch.setattr("backend.src.routers.languages._uploaded_zip", reject_multipart)
        expected_detail = "Could not read the uploaded language pack."
    else:

        def reject_pack(_store, _raw):
            raise LanguagePackError("Use a valid language code.") from OSError(private_detail)

        monkeypatch.setattr(LanguagePackStore, "install", reject_pack)
        expected_detail = "Use a valid language code."

    async def exercise():
        async with asgi_client(_application(tmp_path)) as client:
            login = await client.post(
                "/api/admin/login", json={"username": "Alice", "password": "test"}
            )
            assert login.json()["success"]
            response = await client.post(
                "/api/admin/languages", files={"file": ("fr.zip", _archive())}
            )
            assert response.status_code == 400
            assert response.json() == {"detail": expected_detail, "code": "invalid_language_pack"}
            assert private_detail not in response.text

    asyncio.run(exercise())
