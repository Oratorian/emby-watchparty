from backend.src.providers.normalization import normalize_details


def test_tagline_prefers_singular_value_then_first_nonempty_array_entry() -> None:
    singular = normalize_details(
        {"Id": "movie-1", "Name": "Arrival", "Tagline": "Primary", "Taglines": ["Backup"]}
    )
    fallback = normalize_details(
        {"Id": "movie-1", "Name": "Arrival", "Tagline": " ", "Taglines": ["", "Backup"]}
    )

    assert singular.tagline == "Primary"
    assert fallback.tagline == "Backup"
