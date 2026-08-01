"""Canonical validation models for inbound Socket.IO events."""

from __future__ import annotations

from functools import wraps
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError


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


class MembersOutbound(OutboundPayload):
    users: list[str] = []
    members: list[dict[str, Any]] = []
    username: str | None = None


class SyncStateOutbound(OutboundPayload):
    current_video: dict[str, Any] | None = None
    playback_state: dict[str, Any]
    users: list[str] = []
    binge_watch: dict[str, Any] | None = None
    pending_auto_advance: dict[str, Any] | None = None


class VideoOutbound(OutboundPayload):
    video: dict[str, Any]


class TimedOutbound(OutboundPayload):
    time: float
    username: str | None = None
    playing: bool | None = None


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


class ToggleLibraryOutbound(OutboundPayload):
    show: bool


class HostOutbound(OutboundPayload):
    host_username: str | None = None
    host_client_id: str | None = None
    is_admin: bool = False
    unlocked: bool = False
    reason: str | None = None


class VoteOutbound(OutboundPayload):
    result: str | None = None
    username: str | None = None
    yes: int | None = None
    no: int | None = None
    required: int | None = None
    reason: str | None = None


class BingeStateOutbound(OutboundPayload):
    available: bool
    active: bool


class AutoAdvanceOutbound(OutboundPayload):
    next_item_id: str | None = None
    next_title: str | None = None
    next_index_number: int | None = None
    total_episodes: int | None = None
    deadline: str | None = None
    countdown_seconds: int | None = None
    reason: str | None = None


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
    "join_vote_started": VoteOutbound,
    "join_vote_pending": VoteOutbound,
    "join_vote_update": VoteOutbound,
    "join_vote_resolved": VoteOutbound,
    "join_rejected": VoteOutbound,
    "binge_watch_state_changed": BingeStateOutbound,
    "auto_advance_pending": AutoAdvanceOutbound,
    "auto_advance_cancelled": AutoAdvanceOutbound,
    "auto_advance_fired": AutoAdvanceOutbound,
    "binge_finished": AutoAdvanceOutbound,
    "party_dissolved": PartyDissolvedOutbound,
    "error": MessageOutbound,
}


def install_inbound_validation(sio: Any, logger: Any = None) -> None:
    """Wrap registered handlers without changing valid wire payloads."""
    namespace_handlers = sio.handlers.get("/", {})
    for event, model in INBOUND_MODELS.items():
        handler = namespace_handlers.get(event)
        if handler is None or getattr(handler, "_payload_validated", False):
            continue

        @wraps(handler)
        async def validated(sid: str, data: Any, _handler=handler,
                            _model=model, _event=event):
            started = perf_counter()
            party_id = data.get("party_id", "-") if isinstance(data, dict) else "-"
            try:
                _model.model_validate(data)
            except ValidationError:
                if logger:
                    logger.info(
                        "event event=%s party=%s latency_ms=%.1f outcome=invalid retry=0",
                        _event, party_id, (perf_counter() - started) * 1000,
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
                        _event, party_id, (perf_counter() - started) * 1000, outcome,
                    )

        validated._payload_validated = True
        namespace_handlers[event] = validated
