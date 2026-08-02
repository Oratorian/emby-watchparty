"""Canonical validation models for inbound Socket.IO events."""

from __future__ import annotations

from functools import wraps
from time import perf_counter
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    import logging

    import socketio


class SocketPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class PartyPayload(SocketPayload):
    party_id: str


class TimedPartyPayload(PartyPayload):
    time: float


class SeekPayload(TimedPartyPayload):
    was_playing: bool = False


class JoinPartyPayload(PartyPayload):
    username: str = ""
    client_id: str = ""
    avatar_uuid: str | None = None


class JoinVotePayload(PartyPayload):
    vote: Literal["yes", "no"]


class UpdateAvatarPayload(PartyPayload):
    avatar_uuid: str | None = None


class ChatPayload(PartyPayload):
    message: str


class ToggleLibraryPayload(PartyPayload):
    show: bool


class SelectVideoPayload(PartyPayload):
    item_id: str
    item_name: str = "Unknown"
    item_overview: str = ""
    media_source_id: str | None = None
    start_seconds: float = 0.0
    quality: str | None = None


class ChangeStreamsPayload(PartyPayload):
    audio_index: int | None = None
    subtitle_index: int | None = None
    quality: str | None = None


class BingeWatchPayload(PartyPayload):
    active: bool


INBOUND_MODELS: dict[str, type[SocketPayload]] = {
    "join_party": JoinPartyPayload,
    "leave_party": PartyPayload,
    "join_vote": JoinVotePayload,
    "update_avatar": UpdateAvatarPayload,
    "chat_message": ChatPayload,
    "toggle_library": ToggleLibraryPayload,
    "select_video": SelectVideoPayload,
    "stop_video": PartyPayload,
    "change_streams": ChangeStreamsPayload,
    "video_ended": PartyPayload,
    "auto_advance_cancel": PartyPayload,
    "set_binge_watch_active": BingeWatchPayload,
    "report_progress": TimedPartyPayload,
    "stream_ready": PartyPayload,
    "heartbeat": TimedPartyPayload,
    "play": TimedPartyPayload,
    "pause": TimedPartyPayload,
    "seek": SeekPayload,
}


class OutboundPayload(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class EmptyOutbound(OutboundPayload):
    pass


class MessageOutbound(OutboundPayload):
    message: str


class ConnectedOutbound(OutboundPayload):
    sid: str


class MemberOutbound(OutboundPayload):
    username: str
    avatar_uuid: str | None = None


class PlaybackStateOutbound(OutboundPayload):
    playing: bool
    time: float
    last_update: str


class VideoStateOutbound(OutboundPayload):
    item_id: str
    title: str
    overview: str = ""
    stream_url: str | None = None
    audio_index: int | None = None
    subtitle_index: int | None = None
    media_source_id: str | None = None
    selected_by: str | None = None
    quality: str | None = None
    item_type: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    episode_index: int | None = None
    episode_count: int | None = None
    next_item_id: str | None = None
    next_item_title: str | None = None
    run_time_seconds: float | None = None


class BingeWatchStateOutbound(OutboundPayload):
    available: bool
    active: bool


class PendingAutoAdvanceOutbound(OutboundPayload):
    next_item_id: str | None = None
    next_title: str | None = None
    next_index_number: int | None = None
    total_episodes: int | None = None
    deadline: str | None = None
    countdown_seconds: int | None = None


class MembersOutbound(OutboundPayload):
    users: list[str] = []
    members: list[MemberOutbound] = []
    username: str | None = None
    rejoin: bool | None = None


class SyncStateOutbound(OutboundPayload):
    current_video: VideoStateOutbound | None = None
    playback_state: PlaybackStateOutbound
    users: list[str] = []
    binge_watch: BingeWatchStateOutbound | None = None
    pending_auto_advance: PendingAutoAdvanceOutbound | None = None


class VideoOutbound(OutboundPayload):
    video: VideoStateOutbound


class TimedOutbound(OutboundPayload):
    time: float
    username: str | None = None
    playing: bool | None = None
    auto_binge: bool | None = None
    wait_for_ready: bool | None = None


class StreamChangedOutbound(VideoOutbound):
    current_time: float
    was_playing: bool


class ReadyOutbound(OutboundPayload):
    ready: list[str] = []
    waiting: list[str] = []


class ChatOutbound(OutboundPayload):
    username: str
    message: str
    avatar_uuid: str | None = None
    timestamp: str


class ToggleLibraryOutbound(OutboundPayload):
    show: bool


class HostOutbound(OutboundPayload):
    host_username: str | None = None
    host_client_id: str | None = None
    is_admin: bool = False
    unlocked: bool = False
    reason: str | None = None
    playing_only: bool | None = None


class VoteStartedOutbound(OutboundPayload):
    username: str
    timeout_seconds: int
    eligible_voters: list[str]
    required_majority: int


class VotePendingOutbound(OutboundPayload):
    timeout_seconds: int
    eligible_voters: list[str]
    required_majority: int


class VoteUpdateOutbound(OutboundPayload):
    votes: dict[str, Literal["yes", "no"]]
    remaining: int


class VoteResolvedOutbound(OutboundPayload):
    result: Literal["pass", "fail", "cancelled"]
    reason: str | None = None


class BingeStateOutbound(OutboundPayload):
    available: bool
    active: bool


class AutoAdvancePendingOutbound(OutboundPayload):
    next_item_id: str
    next_title: str
    next_index_number: int | None = None
    total_episodes: int
    deadline: str
    countdown_seconds: int


class AutoAdvanceFiredOutbound(OutboundPayload):
    next_item_id: str
    next_title: str


class AutoAdvanceCancelledOutbound(OutboundPayload):
    by_username: str | None = None


class BingeFinishedOutbound(OutboundPayload):
    reason: str | None = None
    series_id: str | None = None
    season_id: str | None = None


class PartyDissolvedOutbound(OutboundPayload):
    party_id: str
    reason: str


OUTBOUND_MODELS: dict[str, type[OutboundPayload]] = {
    "connected": ConnectedOutbound,
    "user_joined": MembersOutbound,
    "user_left": MembersOutbound,
    "members_update": MembersOutbound,
    "sync_state": SyncStateOutbound,
    "video_selected": VideoOutbound,
    "video_stopped": EmptyOutbound,
    "video_ended": EmptyOutbound,
    "play": TimedOutbound,
    "pause": TimedOutbound,
    "seek": TimedOutbound,
    "streams_changed": StreamChangedOutbound,
    "ready_check_update": ReadyOutbound,
    "all_ready": TimedOutbound,
    "force_pause_before_seek": TimedOutbound,
    "drift_correction": TimedOutbound,
    "chat_message": ChatOutbound,
    "toggle_library": ToggleLibraryOutbound,
    "host_changed": HostOutbound,
    "host_left": HostOutbound,
    "host_reclaimed": HostOutbound,
    "join_vote_started": VoteStartedOutbound,
    "join_vote_pending": VotePendingOutbound,
    "join_vote_update": VoteUpdateOutbound,
    "join_vote_resolved": VoteResolvedOutbound,
    "join_rejected": MessageOutbound,
    "binge_watch_state_changed": BingeStateOutbound,
    "auto_advance_pending": AutoAdvancePendingOutbound,
    "auto_advance_cancelled": AutoAdvanceCancelledOutbound,
    "auto_advance_fired": AutoAdvanceFiredOutbound,
    "binge_finished": BingeFinishedOutbound,
    "party_dissolved": PartyDissolvedOutbound,
    "error": MessageOutbound,
}


def install_outbound_validation(
    sio: socketio.AsyncServer,
    logger: logging.Logger | None = None,
) -> None:
    """Validate every known server event while preserving its wire payload."""
    if getattr(sio, "_outbound_payload_validated", False):
        return
    original_emit = sio.emit

    @wraps(original_emit)
    async def validated_emit(
        event: str,
        data: object = None,
        *args: object,
        **kwargs: object,
    ) -> object:
        model = OUTBOUND_MODELS.get(event)
        if model is not None:
            try:
                model.model_validate(data if data is not None else {})
            except ValidationError as exc:
                if logger:
                    logger.error(
                        "event event=%s party=- outcome=invalid_outbound",
                        event,
                    )
                raise ValueError(f"Invalid outbound {event} payload") from exc
        return await original_emit(event, data, *args, **kwargs)

    setattr(sio, "emit", validated_emit)  # noqa: B010 - runtime Socket.IO decorator
    setattr(sio, "_outbound_payload_validated", True)  # noqa: B010


def install_inbound_validation(
    sio: socketio.AsyncServer,
    logger: logging.Logger | None = None,
) -> None:
    """Wrap registered handlers without changing valid wire payloads."""
    namespace_handlers = sio.handlers.get("/", {})
    for event, model in INBOUND_MODELS.items():
        handler = namespace_handlers.get(event)
        if handler is None or getattr(handler, "_payload_validated", False):
            continue

        @wraps(handler)
        async def validated(
            sid: str,
            data: object,
            _handler=handler,
            _model=model,
            _event=event,
        ) -> object:
            started = perf_counter()
            party_id = data.get("party_id", "-") if isinstance(data, dict) else "-"
            try:
                _model.model_validate(data)
            except ValidationError:
                if logger:
                    logger.info(
                        "event event=%s party=%s latency_ms=%.1f outcome=invalid retry=0",
                        _event,
                        party_id,
                        (perf_counter() - started) * 1000,
                    )
                await sio.emit(
                    "error",
                    {"message": f"Invalid {_event} payload"},
                    to=sid,
                )
                return None
            try:
                result = await _handler(sid, data)
            except Exception:
                outcome = "error"
                raise
            else:
                outcome = "ok"
                return result
            finally:
                if logger:
                    logger.info(
                        "event event=%s party=%s latency_ms=%.1f outcome=%s retry=0",
                        _event,
                        party_id,
                        (perf_counter() - started) * 1000,
                        outcome,
                    )

        setattr(validated, "_payload_validated", True)  # noqa: B010
        namespace_handlers[event] = validated
