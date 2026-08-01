"""Canonical validation models for inbound Socket.IO events."""

from __future__ import annotations

from functools import wraps
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


def install_inbound_validation(sio: Any) -> None:
    """Wrap registered handlers without changing valid wire payloads."""
    namespace_handlers = sio.handlers.get("/", {})
    for event, model in INBOUND_MODELS.items():
        handler = namespace_handlers.get(event)
        if handler is None or getattr(handler, "_payload_validated", False):
            continue

        @wraps(handler)
        async def validated(sid: str, data: Any, _handler=handler,
                            _model=model, _event=event):
            try:
                _model.model_validate(data)
            except ValidationError:
                await sio.emit(
                    "error",
                    {"message": f"Invalid {_event} payload"},
                    to=sid,
                )
                return None
            return await _handler(sid, data)

        validated._payload_validated = True
        namespace_handlers[event] = validated
