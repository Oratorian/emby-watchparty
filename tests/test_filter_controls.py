"""Presentation rules the filter rail depends on, at the layer that serves it.

The parental-rating ordering had a unit test from the day it was written and
was still lost, because the test called the helper directly while the helper
was reachable only from the retired `/api/items/filter-options`. The v2 route
the frontend actually calls went straight to the provider and never applied
it. So these tests go through `get_filter_controls`, which is what v2 calls,
rather than through the sorting function on its own.
"""

import asyncio

import pytest

from backend.src.providers.emby import EmbyProvider
from backend.src.providers.models import ProviderCredentials
from backend.src.providers.normalization import prioritize_parental_ratings
from tests.support.credentials import TEST_JELLYFIN_ACCESS_TOKEN

# Deliberately shuffled, and deliberately mixing US movie certificates with
# TV ratings and a regional board, which is what a real library that has ever
# imported anything from outside one country returns.
_UNORDERED_RATINGS = (
    "12+",
    "R",
    "PG-13",
    "TV-MA",
    "G",
    "PG",
    "NC-17",
    "NR",
    "Not Rated",
    "Approved",
)


class _StubClient:
    """Answers get_filter_options and nothing else."""

    def __init__(self, ratings: tuple[str, ...]):
        self._ratings = ratings
        self.gateway = None

    async def get_filter_options(self, **_kwargs) -> dict:
        return {
            "official_rating": {"Items": [{"Name": name} for name in self._ratings]},
            "genre": {"Items": [{"Name": "Drama"}]},
        }


def _controls(ratings: tuple[str, ...]) -> list[dict]:
    provider = EmbyProvider(_StubClient(ratings), config=None)
    return list(
        asyncio.run(
            provider.get_filter_controls(
                None,
                (),
                (),
                ProviderCredentials(access_token=TEST_JELLYFIN_ACCESS_TOKEN, user_id="user"),
            )
        )
    )


def test_emby_filter_controls_lead_with_familiar_us_movie_ratings() -> None:
    """The order Emby's catalog happens to return is not an order to present.

    Emby answers OfficialRatings in catalog order, so the certificate most
    viewers are scanning for sits wherever the library's import history put
    it. Jellyfin needs no equivalent because its list is a static literal
    already in this order.
    """
    controls = _controls(_UNORDERED_RATINGS)

    official = next(control for control in controls if control["id"] == "official_rating")
    assert [value["value"] for value in official["values"]] == [
        "G",
        "PG",
        "PG-13",
        "R",
        "NC-17",
        "NR",
        "Not Rated",
        "12+",
        "TV-MA",
        "Approved",
    ]


def test_other_controls_keep_the_order_the_server_gave_them() -> None:
    """Only parental ratings are reordered; nothing else has a known ranking."""
    controls = _controls(("R", "G"))

    genre = next(control for control in controls if control["id"] == "genre")
    assert [value["value"] for value in genre["values"]] == ["Drama"]


@pytest.mark.parametrize("spelling", ["not rated", "NOT RATED", " Not Rated "])
def test_ranking_is_case_and_whitespace_insensitive(spelling: str) -> None:
    """Servers disagree on casing for the same certificate.

    The rank is looked up on a stripped, uppercased value, so a library that
    stores "not rated" ranks with one that stores "NR" instead of falling to
    the unranked tail.
    """
    ordered = prioritize_parental_ratings(
        [{"value": "Approved", "label": "Approved"}, {"value": spelling, "label": spelling}]
    )

    assert [value["value"] for value in ordered] == [spelling, "Approved"]
