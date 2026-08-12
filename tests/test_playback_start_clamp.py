"""Resume offsets must land inside the runtime of the source being started.

Emby answers a start at or past the end of media with a zero-length manifest,
which players surface as an immediate `ended`. From the party's selector that
runs video_ended, stopping every viewer's transcode and clearing the video, so
a bad start time for one person ends the film for the room.
"""

import pytest

from backend.src.socket_handlers.playback import (
    END_OF_MEDIA_BUFFER_SECONDS,
    clamp_start_seconds,
    media_source_run_time,
)

# Real shape, from tests/artifacts/emby/4.9.5.0: Emby reports runtime in
# 100-nanosecond ticks, which is the conversion this can get wrong.
THEATRICAL = {"Id": "source-theatrical", "RunTimeTicks": 72_000_000_000}  # 120 min
EXTENDED = {"Id": "source-extended", "RunTimeTicks": 90_000_000_000}  # 150 min


def test_ticks_convert_to_seconds() -> None:
    assert media_source_run_time(THEATRICAL) == 7200.0
    assert media_source_run_time(EXTENDED) == 9000.0


@pytest.mark.parametrize("media_source", [None, {}, {"RunTimeTicks": None}, {"Id": "x"}])
def test_a_source_that_reports_no_runtime_is_not_treated_as_zero_length(media_source) -> None:
    """Unknown runtime must not clamp every start to 0 and restart the film."""
    assert media_source_run_time(media_source) == 0.0
    assert clamp_start_seconds(1234.0, media_source_run_time(media_source)) == 1234.0


def test_switching_to_a_shorter_version_lands_inside_the_new_runtime() -> None:
    """The defect: the party clock belongs to the source being left behind.

    Watching the extended cut at 02:20:00 and switching to the theatrical asked
    Emby for 8400s against a 7200s source.
    """
    party_clock = 8400.0
    assert party_clock > media_source_run_time(THEATRICAL)

    start = clamp_start_seconds(party_clock, media_source_run_time(THEATRICAL))

    assert start == 7200.0 - END_OF_MEDIA_BUFFER_SECONDS
    assert start < media_source_run_time(THEATRICAL)


def test_switching_to_a_longer_version_keeps_the_party_position() -> None:
    """Clamping must not drag viewers backwards when the target is longer."""
    assert clamp_start_seconds(7000.0, media_source_run_time(EXTENDED)) == 7000.0


@pytest.mark.parametrize("start", [-1.0, None, 0.0])
def test_a_missing_or_negative_start_becomes_zero(start) -> None:
    assert clamp_start_seconds(start, media_source_run_time(THEATRICAL)) == 0.0
