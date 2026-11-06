"""Validated, persistent community translation catalogs.

Archives are read as bounded members, never extracted onto the filesystem.
The English source catalog is packaged with the backend so runtime imports do
not require a Node installation or the frontend source tree.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import threading
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024
MAX_PACKS = 32
MAX_MESSAGE_LENGTH = 8000
CATALOG_PATH = Path(__file__).resolve().parents[1] / "language-catalog.json"
_LOCALE = re.compile(
    r"[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3})){0,2}"
)
_NAMED = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_TOKEN = re.compile(r"\{(?:[A-Za-z][A-Za-z0-9_]*|'[^'{}]*')\}")
_BAD_KEYS = frozenset({"__proto__", "prototype", "constructor"})

type MessageTree = dict[str, str | MessageTree]


class LanguagePackError(ValueError):
    """Invalid community input, suitable for a bounded client-facing answer."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def canonical_locale(value: object) -> str:
    if not isinstance(value, str) or not _LOCALE.fullmatch(value):
        raise LanguagePackError("Use a language code such as fr, pt-BR or zh-Hant.")
    parts = value.split("-")
    normalized = [parts[0].lower()]
    normalized.extend(
        part.title()
        if len(part) == 4 and part.isalpha()
        else part.upper()
        if len(part) == 2 and part.isalpha()
        else part.lower()
        for part in parts[1:]
    )
    locale = "-".join(normalized)
    if locale in {"en", "auto"}:
        raise LanguagePackError("English is the built-in fallback and cannot be replaced.")
    return locale


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LanguagePackError("Duplicate JSON keys are not allowed.")
        if key in _BAD_KEYS:
            raise LanguagePackError("Reserved JSON keys are not allowed.")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise LanguagePackError("JSON must not contain non-finite numbers.")


def _unicode_scalars(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode("utf-8")
            _unicode_scalars(item)
    elif isinstance(value, list):
        for item in value:
            _unicode_scalars(item)


def _parse_json(raw: bytes) -> dict:
    try:
        result = json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_invalid_constant
        )
        _unicode_scalars(result)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, LanguagePackError):
            raise
        raise LanguagePackError("Language files must contain valid UTF-8 JSON objects.") from error
    if not isinstance(result, dict):
        raise LanguagePackError("Each language file must contain a JSON object.")
    return result


def _text(value: object, name: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise LanguagePackError(
            f"Manifest {name} must be a string of at most {maximum} characters."
        )
    value = value.strip()
    if required and not value:
        raise LanguagePackError(f"Manifest {name} must not be empty.")
    if any(ord(character) < 32 for character in value) or "<" in value or ">" in value:
        raise LanguagePackError(f"Manifest {name} contains unsupported characters.")
    return value


def _manifest(data: dict) -> dict:
    if set(data) - {"format", "locale", "name", "author", "version"}:
        raise LanguagePackError("The manifest contains an unknown field.")
    if type(data.get("format")) is not int or data["format"] != 1:
        raise LanguagePackError("Unsupported language pack format. Use format 1.")
    return {
        "format": 1,
        "locale": canonical_locale(data.get("locale")),
        "name": _text(data.get("name"), "name", 80, required=True),
        "author": _text(data.get("author", ""), "author", 100),
        "version": _text(data.get("version", ""), "version", 40),
    }


def _flatten(tree: dict, *, depth: int = 0, prefix: str = "") -> dict[str, str]:
    if depth > 8:
        raise LanguagePackError("Translation nesting is too deep.")
    result: dict[str, str] = {}
    for key, value in tree.items():
        if not isinstance(key, str) or not key or "." in key or key in _BAD_KEYS:
            raise LanguagePackError("Translation keys must be nonempty object keys without dots.")
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, str):
            result[path] = value
        elif isinstance(value, dict):
            result.update(_flatten(value, depth=depth + 1, prefix=path))
        else:
            raise LanguagePackError("Translation values must be strings or nested objects.")
    return result


def _validate_message(message: str, original: str, key: str) -> None:
    if not message.strip() or len(message) > MAX_MESSAGE_LENGTH:
        raise LanguagePackError(f"Translation {key[:120]} is empty or too long.")
    if "<" in message or ">" in message:
        raise LanguagePackError("Language packs contain text only, without HTML.")
    for token in _TOKEN.finditer(message):
        literal = token.group()
        if literal.startswith("{'") and (
            "\\" in literal or any(ord(character) < 32 for character in literal)
        ):
            raise LanguagePackError(
                "Quoted literals must not contain backslashes or control characters."
            )
    remaining = _TOKEN.sub("", message)
    if any(character in remaining for character in "{}@"):
        raise LanguagePackError("Use named placeholders, literal escapes and plain text only.")
    if any(not branch.strip() for branch in message.split("|")):
        raise LanguagePackError("Plural forms must not be empty.")
    if set(_NAMED.findall(message)) != set(_NAMED.findall(original)):
        raise LanguagePackError(f"Translation placeholders do not match English for {key[:120]}.")


def _validate_structure(messages: dict, english: MessageTree, *, depth: int = 0) -> None:
    if not isinstance(messages, dict) or depth > 8:
        raise LanguagePackError("Translation values must follow the English catalog structure.")
    for key, value in messages.items():
        if key not in english:
            raise LanguagePackError("The pack contains an unknown translation key.")
        original = english[key]
        if isinstance(original, str):
            if not isinstance(value, str):
                raise LanguagePackError("Translation message values must be strings.")
        else:
            _validate_structure(value, original, depth=depth + 1)


def _serialized(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class LanguagePack:
    manifest: dict
    messages: MessageTree
    revision: str

    def summary(self) -> dict:
        return {key: self.manifest[key] for key in ("locale", "name", "author", "version")} | {
            "revision": self.revision
        }

    def payload(self) -> dict:
        return {
            "locale": self.manifest["locale"],
            "revision": self.revision,
            "messages": self.messages,
        }


class LanguagePackStore:
    def __init__(self, directory: Path, *, catalog_path: Path = CATALOG_PATH):
        self.directory = Path(directory)
        self.catalog_path = Path(catalog_path)
        self._lock = threading.RLock()
        self._catalog: MessageTree | None = None
        self._cache: dict[str, tuple[tuple[int, int], LanguagePack | None]] = {}

    def _pack_path(self, locale: str) -> Path:
        directory = os.path.realpath(self.directory)
        expected = str(Path(directory) / f"pack-{canonical_locale(locale)}.json")
        path = os.path.realpath(expected)
        # Resolve before checking containment, and reject pack-file symlinks even
        # when they point at another file inside the configured directory.
        prefix = directory if directory.endswith(os.sep) else f"{directory}{os.sep}"
        if not path.startswith(prefix) or os.path.normcase(path) != os.path.normcase(expected):
            raise LanguagePackError("Language pack files must stay in the language directory.")
        return Path(path)

    def catalog(self) -> MessageTree:
        if self._catalog is not None:
            return self._catalog
        data = _parse_json(self.catalog_path.read_bytes())
        if data.get("format") != 1 or not isinstance(data.get("messages"), dict):
            raise RuntimeError("The packaged language catalog is invalid.")
        self._catalog = data["messages"]
        return self._catalog

    def _validated(self, manifest: dict, messages: dict) -> LanguagePack:
        manifest = _manifest(manifest)
        original = self.catalog()
        if set(messages) - set(original):
            raise LanguagePackError("The pack contains an unknown translation namespace.")
        _validate_structure(messages, original)
        provided = _flatten(messages)
        english = _flatten(original)
        if not provided:
            raise LanguagePackError("A language pack must contain at least one translation.")
        for key, value in provided.items():
            if key not in english:
                raise LanguagePackError(f"Unknown translation key: {key[:120]}.")
            _validate_message(value, english[key], key)
        payload = {"manifest": manifest, "messages": messages}
        serialized = _serialized(payload)
        if len(serialized) > MAX_EXPANDED_BYTES:
            raise LanguagePackError("The complete language pack must fit within 2 MiB.")
        revision = hashlib.sha256(serialized).hexdigest()
        return LanguagePack(manifest=manifest, messages=messages, revision=revision)

    def parse_archive(self, raw: bytes) -> LanguagePack:
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise LanguagePackError("ZIP files must be no larger than 1 MiB.")
        namespaces = set(self.catalog())
        allowed = {"manifest.json", *(f"{name}.json" for name in namespaces)}
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > min(32, len(allowed)):
                    raise LanguagePackError("The ZIP contains too many files.")
                if len({entry.filename.casefold() for entry in entries}) != len(entries):
                    raise LanguagePackError("Duplicate ZIP filenames are not allowed.")
                if sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                    raise LanguagePackError("Expanded language files must fit within 2 MiB.")
                files = {}
                total = 0
                for entry in entries:
                    mode = entry.external_attr >> 16
                    if (
                        entry.filename not in allowed
                        or entry.is_dir()
                        or entry.flag_bits & 1
                        or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                        or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    ):
                        raise LanguagePackError(
                            "The ZIP must contain only root-level language JSON files."
                        )
                    with archive.open(entry) as source:
                        member = source.read(MAX_EXPANDED_BYTES - total + 1)
                    total += len(member)
                    if total > MAX_EXPANDED_BYTES:
                        raise LanguagePackError("Expanded language files must fit within 2 MiB.")
                    files[entry.filename] = _parse_json(member)
        except (
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            OSError,
            zlib.error,
        ) as error:
            raise LanguagePackError("Could not read the ZIP archive.") from error
        if "manifest.json" not in files:
            raise LanguagePackError("The ZIP must contain manifest.json.")
        manifest = files.pop("manifest.json")
        return self._validated(manifest, {name[:-5]: value for name, value in files.items()})

    def install(self, raw: bytes) -> LanguagePack:
        pack = self.parse_archive(raw)
        payload = _serialized({"manifest": pack.manifest, "messages": pack.messages})
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            destination = self._pack_path(pack.manifest["locale"])
            if (
                not destination.exists()
                and len(list(self.directory.glob("pack-*.json"))) >= MAX_PACKS
            ):
                raise LanguagePackError("Remove a language pack before installing another.")
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=self.directory, prefix=".language-", delete=False
                ) as out:
                    temporary = Path(out.name)
                    out.write(payload)
                    out.flush()
                    os.fsync(out.fileno())
                temporary.replace(destination)
            finally:
                if temporary is not None:
                    with contextlib.suppress(FileNotFoundError):
                        temporary.unlink()
        return pack

    def get(self, locale: str) -> LanguagePack | None:
        canonical = canonical_locale(locale)
        path = self._pack_path(canonical)
        with self._lock:
            try:
                info = path.stat()
                if info.st_size > MAX_EXPANDED_BYTES:
                    return None
                stamp = (info.st_mtime_ns, info.st_size)
                cached = self._cache.get(canonical)
                if cached is not None and cached[0] == stamp:
                    return cached[1]
                data = _parse_json(path.read_bytes())
            except FileNotFoundError:
                self._cache.pop(canonical, None)
                return None
            except LanguagePackError:
                return None
            try:
                pack = self._validated(data.get("manifest", {}), data.get("messages", {}))
            except (LanguagePackError, TypeError, AttributeError):
                return None
            result = pack if pack.manifest["locale"] == canonical else None
            self._cache[canonical] = (stamp, result)
            return result

    def list(self) -> list[LanguagePack]:
        with self._lock:
            packs = []
            for path in sorted(self.directory.glob("pack-*.json"))[:MAX_PACKS]:
                try:
                    pack = self.get(path.stem.removeprefix("pack-"))
                except LanguagePackError:
                    continue
                if pack is not None:
                    packs.append(pack)
            return packs

    def delete(self, locale: str) -> bool:
        canonical = canonical_locale(locale)
        with self._lock:
            try:
                self._pack_path(canonical).unlink()
            except FileNotFoundError:
                return False
            self._cache.pop(canonical, None)
        return True

    def template(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": 1,
                        "locale": "fr",
                        "name": "Français",
                        "author": "",
                        "version": "1.0",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            for namespace, messages in self.catalog().items():
                archive.writestr(
                    f"{namespace}.json", json.dumps(messages, ensure_ascii=False, indent=2)
                )
        return buffer.getvalue()
