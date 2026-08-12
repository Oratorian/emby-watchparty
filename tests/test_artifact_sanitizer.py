"""The sanitizer that writes tests/artifacts must default to denying.

This is the tool that leaked. The committed corpus is checked elsewhere
(test_emby_artifacts.py), but checking the output only proves the files that
exist today are clean -- it says nothing about what the next capture will
write, and the corpus is regenerated against a real, private Emby server and
committed to a public repo. The three defects that caused the leak were all
in here, and all three are invisible from the output side:

  - `Sanitizer.value` fell through to `return value` for unrecognised keys,
    so SortName, ForcedSortName, FileName and ServerName shipped verbatim
    beside the very Name they were meant to anonymise;
  - the `providerid` rule sat below the dict branch, so it could never fire
    and every external id went out in the clear;
  - nothing exercised the sanitizer at all.

So these drive `Sanitizer` directly, and lead with the property rather than
the enumeration: anything not explicitly allowed comes out redacted.
"""

import json

from scripts.capture_emby_artifacts import (
    PRIVATE_KEY_PARTS,
    SEMANTIC_STRINGS,
    TITLE_STRINGS,
    Sanitizer,
)

# Shaped like a real Emby item, with something to leak in every field that had
# one. Every value here is invented. It has to carry the SHAPE of the data that
# leaked, since that is what the sanitizer's rules key on, but a fixture in a
# public repo is the last place to reach for a real hostname or a real external
# id -- and this file would not be caught by the corpus scanner, which walks
# tests/artifacts and nothing else.
REAL_ITEM = {
    "Id": "0123456789abcdef0123456789abcdef",
    "Name": "Placeholder Title",
    "SortName": "Placeholder Title, The",
    "ForcedSortName": "Placeholder Title, The",
    "ServerName": "DESKTOP-EXAMPLE0",
    "Path": "/mnt/example/Films/Placeholder Title (2001)/Placeholder Title.mkv",
    "Type": "Movie",
    "Container": "mkv",
    "ProviderIds": {"Imdb": "tt0000000", "Tmdb": "000000"},
    "MediaSources": [
        {
            "Id": "b0a1",
            "Name": "Placeholder Title",
            "Path": "/mnt/example/Films/Placeholder Title (2001)/Placeholder Title.mkv",
            "Container": "mkv",
        }
    ],
}


def _leaks(payload: object) -> list[str]:
    """Every string still present anywhere in the sanitized tree."""
    text = json.dumps(payload)
    return [
        secret
        for secret in (
            "Placeholder Title",
            "Placeholder Title, The",
            "DESKTOP-EXAMPLE0",
            "/mnt/example",
            "tt0000000",
            "000000",
            "0123456789abcdef0123456789abcdef",
        )
        if secret in text
    ]


def test_nothing_recognisable_survives_a_real_item() -> None:
    assert _leaks(Sanitizer().value(REAL_ITEM)) == []


def test_an_unrecognised_key_is_redacted_rather_than_published() -> None:
    """The default-deny rule, stated as the property it is.

    Enumerating the keys that leaked would only re-pin the ones already known.
    Emby adds fields between versions, and a capture tool writing into a public
    repo has to treat an unknown key as one nobody has decided is safe.
    """
    sanitized = Sanitizer().value({"AKeyNoOneHasEverSeen": "Something private", "Name": "A Title"})
    assert sanitized["AKeyNoOneHasEverSeen"] == "<akeynoonehaseverseen>"
    assert "Something private" not in json.dumps(sanitized)


def test_provider_ids_stay_a_dict_while_their_values_are_redacted() -> None:
    """The corpus exists to lock response shape, so redaction must preserve it.

    This is also where the leak lived: the private-key test sat below the dict
    branch, so on a dict-valued key like ProviderIds it never ran.
    """
    sanitized = Sanitizer().value(REAL_ITEM)

    assert isinstance(sanitized["ProviderIds"], dict)
    assert set(sanitized["ProviderIds"]) == {"Imdb", "Tmdb"}
    assert all(v.startswith("<") for v in sanitized["ProviderIds"].values())
    assert isinstance(sanitized["MediaSources"], list)
    assert set(sanitized["MediaSources"][0]) == {"Id", "Name", "Path", "Container"}


def test_privacy_is_inherited_by_everything_under_a_private_key() -> None:
    """Probed through a key that is otherwise allowed to pass through verbatim.

    Default-deny alone would redact an unrecognised nested key, which masks
    whether the flag is inherited at all. The two rules only come apart under
    a key on an allowlist: without inheritance, `Container` below `Path`
    returns its value unchanged, because being nested under something private
    is the only thing that made it private.
    """
    nested = Sanitizer().value({"Path": {"Container": "example-share", "Deep": "secret"}})
    assert "example-share" not in json.dumps(nested)
    assert "secret" not in json.dumps(nested)

    # Lists carry it too, so a private key holding a list of dicts is covered.
    listed = Sanitizer().value({"ProviderIds": [{"Type": "tt0000000"}]})
    assert "tt0000000" not in json.dumps(listed)


def test_semantic_values_survive_because_the_corpus_asserts_on_them() -> None:
    """Redacting these would make the corpus useless rather than merely safe."""
    sanitized = Sanitizer().value(REAL_ITEM)
    assert sanitized["Type"] == "Movie"
    assert sanitized["Container"] == "mkv"


def test_the_same_title_maps_to_the_same_placeholder() -> None:
    """Two fields naming one title must still agree, or the shape is a lie."""
    sanitizer = Sanitizer()
    first = sanitizer.value({"Name": "Alpha", "SeriesName": "Alpha", "Album": "Beta"})
    assert first["Name"] == first["SeriesName"]
    assert first["Name"] != first["Album"]

    # And across calls, since a capture walks many responses with one sanitizer.
    second = sanitizer.value({"OriginalTitle": "Alpha"})
    assert second["OriginalTitle"] == first["Name"]


def test_ids_are_mapped_consistently_and_never_pass_through() -> None:
    sanitizer = Sanitizer()
    sanitized = sanitizer.value({"Id": "abc123", "SeasonId": "abc123", "ParentId": "def456"})
    assert sanitized["Id"] == sanitized["SeasonId"]
    assert sanitized["Id"] != sanitized["ParentId"]
    assert "abc123" not in json.dumps(sanitized)


def test_urls_and_filesystem_paths_are_replaced() -> None:
    sanitized = Sanitizer().value(
        {
            "Overview": "https://emby.example.internal/library",
            "Tagline": "C:\\Users\\Someone\\Media",
        }
    )
    assert "emby.example.internal" not in json.dumps(sanitized)
    assert "Someone" not in json.dumps(sanitized)


def test_non_strings_are_left_alone_so_the_shape_still_type_checks() -> None:
    sanitized = Sanitizer().value(
        {"RunTimeTicks": 72_000_000_000, "IsFolder": False, "Missing": None}
    )
    assert sanitized == {"RunTimeTicks": 72_000_000_000, "IsFolder": False, "Missing": None}


def test_the_private_key_list_still_covers_what_leaked() -> None:
    """Guards the specific parts whose absence caused the incident."""
    for part in ("token", "password", "path", "username", "providerid", "filename"):
        assert part in PRIVATE_KEY_PARTS


def test_the_allowlists_have_not_quietly_absorbed_a_title_field() -> None:
    """SortName et al. belong to neither list; that is what default-deny fixed."""
    for leaked in ("SortName", "ForcedSortName", "FileName", "ServerName"):
        assert leaked not in TITLE_STRINGS
        assert leaked not in SEMANTIC_STRINGS
