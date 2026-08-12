"""Per-viewer video codec negotiation (issue #61).

Streams are built per viewer, so which codec a source is delivered in is a
property of the browser asking, not of the party. Before this, `VideoCodec`
was hardcoded to h264 for every stream, so an HEVC source was re-encoded even
for a client that would have played it directly.

These pin both directions, because the failure modes are opposite and both
matter: not re-encoding for a client that can decode, and never handing HEVC
to one that cannot. The second is the dangerous one, since in a synchronised
party it leaves exactly one person with a black video.
"""

import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.src.socket_protocol import JoinPartyPayload
from backend.src.stream_builder import StreamBuilder


def _builder():
    # Only device_id is read off the client here; the builder makes no calls.
    emby = SimpleNamespace(device_id="test-device")
    return StreamBuilder(emby_client=emby, logger=logging.getLogger("test"), config=None)


def _source(codec: str, bitrate: int = 4_626_346) -> dict:
    return {
        "MediaStreams": [
            {"Type": "Video", "Codec": codec, "BitRate": bitrate, "Width": 1920},
            {"Type": "Audio", "Codec": "ac3", "Index": 1},
        ]
    }


def _params(codec: str, client_codecs=None, quality: str = "auto") -> dict:
    raw = _builder().build_params(
        _source(codec),
        media_source_id="ms-1",
        play_session_id="ps-1",
        audio_index=1,
        subtitle_index=None,
        quality=quality,
        client_codecs=client_codecs,
    )
    return dict(part.split("=", 1) for part in raw if "=" in part)


def test_hevc_source_stays_hevc_for_a_client_that_decodes_it():
    params = _params("hevc", client_codecs={"h264", "hevc"})

    assert params["VideoCodec"] == "hevc"
    # TranscodeReasons is what Emby logs; claiming the codec is unsupported
    # while asking for that same codec is contradictory, and it was the
    # reason the report pointed at even though it is only informational.
    assert "TranscodeReasons" not in params


def test_hevc_source_is_transcoded_for_a_client_that_cannot_decode_it():
    params = _params("hevc", client_codecs={"h264"})

    assert params["VideoCodec"] == "h264"
    assert params["TranscodeReasons"] == "VideoCodecNotSupported"


def test_a_client_that_reports_nothing_is_treated_as_h264_only():
    """Old clients and clients whose probe failed must keep working.

    An unpatched frontend sends no codec list at all, and the safe reading of
    silence is the codec every target browser decodes.
    """
    params = _params("hevc", client_codecs=None)

    assert params["VideoCodec"] == "h264"
    assert params["TranscodeReasons"] == "VideoCodecNotSupported"


def test_h264_source_still_stream_copies_on_auto():
    """The pre-existing fast path must not regress.

    An h264 source under Auto sets no TranscodeReasons, which is what lets
    Emby stream-copy instead of re-encoding.
    """
    params = _params("h264", client_codecs={"h264", "hevc"})

    assert params["VideoCodec"] == "h264"
    assert "TranscodeReasons" not in params


def test_an_explicit_bitrate_cap_still_forces_a_transcode_of_a_kept_codec():
    """Keeping the codec is not the same as refusing to transcode.

    A viewer who picks a bitrate below the source still gets a re-encode; the
    negotiated codec only decides what it is re-encoded *to*.
    """
    params = _params("hevc", client_codecs={"h264", "hevc"}, quality="1080p-4000")

    assert params["VideoCodec"] == "hevc"
    assert params["VideoBitrate"] == "4000000"


def test_two_viewers_of_the_same_source_can_get_different_codecs():
    """The point of doing this per viewer rather than per party."""
    capable = _params("hevc", client_codecs={"h264", "hevc"})
    incapable = _params("hevc", client_codecs={"h264"})

    assert capable["VideoCodec"] == "hevc"
    assert incapable["VideoCodec"] == "h264"


def test_a_codec_the_client_invents_is_never_echoed_into_the_url():
    """build_params must not be a way to put arbitrary text in VideoCodec=.

    The socket handler allowlists before this point, but the builder is the
    thing that writes the URL, so it should not depend on being called
    correctly.
    """
    params = _params("hevc", client_codecs={"h264", "; DROP TABLE"})

    assert params["VideoCodec"] == "h264"


def test_client_codec_claims_are_allowlisted_before_they_reach_the_builder():
    """The socket handler is the trust boundary for this value.

    It ends up in an Emby stream URL, so an unconstrained string would let a
    client write arbitrary text into VideoCodec=. h264 is always added back,
    so a client that claims nothing, or only nonsense, still gets a stream.
    """
    from backend.src.socket_handlers.party import _parse_client_codecs

    assert _parse_client_codecs(["h264", "hevc"]) == {"h264", "hevc"}
    assert _parse_client_codecs(["HEVC"]) == {"h264", "hevc"}
    assert _parse_client_codecs(["hevc", "definitely-not-a-codec"]) == {"h264", "hevc"}
    assert _parse_client_codecs([]) == {"h264"}

    # Shapes an unpatched or hostile client can send.
    assert _parse_client_codecs(None) == {"h264"}
    assert _parse_client_codecs("hevc") == {"h264"}
    assert _parse_client_codecs({"hevc": True}) == {"h264"}
    assert _parse_client_codecs([1, None, {"x": 1}]) == {"h264"}


def test_a_join_that_predates_this_field_still_validates():
    """join_party is a strict typed contract here, unlike on 2.x.

    So the field being optional is not a nicety: if a missing video_codecs
    failed validation, an unpatched client could not join the party at all.
    Losing the party is a far worse outcome than losing a stream copy.
    """
    payload = JoinPartyPayload.model_validate(
        {"party_id": "p-1", "username": "Alice", "client_id": "c-1"}
    )

    assert payload.video_codecs == []

    from backend.src.socket_handlers.party import _parse_client_codecs

    assert _parse_client_codecs(payload.video_codecs) == {"h264"}


@pytest.mark.parametrize("malformed", ["hevc", None, [1], {"hevc": True}, [None]])
def test_strict_validation_rejects_a_codec_list_of_the_wrong_shape(malformed):
    """Strict validation is the first gate, ahead of the allowlist.

    _parse_client_codecs defends against these shapes too, and keeps doing so
    because it is also reachable from the 2.x-shaped payload, but on 3.0
    nothing of the wrong type gets that far. Pinned so that a later loosening
    of the contract cannot quietly move the trust boundary.
    """
    with pytest.raises(ValidationError):
        JoinPartyPayload.model_validate({"party_id": "p-1", "video_codecs": malformed})


def test_a_declared_codec_list_reaches_the_handler_uncoerced():
    payload = JoinPartyPayload.model_validate({"party_id": "p-1", "video_codecs": ["hevc", "h264"]})

    assert payload.video_codecs == ["hevc", "h264"]
