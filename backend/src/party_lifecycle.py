"""Central ownership and teardown for watch-party resources."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from backend.src.domain import Party


class PartyLifecycle:
    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._sio = ctx["sio"]
        self._emby = ctx["emby_client"]
        self._parties = ctx["party_manager"]
        self._tokens = ctx["token_manager"]
        self._logger = ctx["logger"]

    async def dissolve_if_empty(self, party_id: str) -> bool:
        party = await self._parties.pop_if_empty(party_id)
        if party is None:
            return False
        await self._cleanup(party_id, party)
        return True

    async def dissolve(self, party_id: str, *, reason: str = "dissolved") -> bool:
        party = await self._parties.pop_party(party_id)
        if party is None:
            return False
        with suppress(Exception):
            await self._sio.emit(
                "party_dissolved",
                {"party_id": party_id, "reason": reason},
                room=party_id,
            )
        await self._cleanup(party_id, party)
        return True

    async def dissolve_all(self, *, reason: str = "shutdown") -> None:
        for party_id in list(self._parties.get_all()):
            await self.dissolve(party_id, reason=reason)

    async def _cleanup(self, party_id: str, party: Party) -> None:
        current = asyncio.current_task()
        tasks: list[asyncio.Task] = []
        pending_join = party.pending_join
        pending_auto = party.pending_auto_advance
        for task in (
            pending_join.timeout_task if pending_join else None,
            pending_auto.task if pending_auto else None,
            self._ctx.get("pending_host_clear", {}).pop(party_id, None),
        ):
            if isinstance(task, asyncio.Task) and task is not current and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        video = party.current_video or {}
        access_token = party.host_access_token
        user_id = party.host_user_id
        position = party.playback_state.time
        for stream in list((party.user_streams or {}).values()):
            play_session_id = stream.play_session_id
            if not play_session_id:
                continue
            if video.get("item_id"):
                with suppress(Exception):
                    await self._emby.report_playback_stopped(
                        item_id=video["item_id"],
                        media_source_id=stream.media_source_id,
                        play_session_id=play_session_id,
                        position_seconds=position,
                        run_time_seconds=video.get("run_time_seconds"),
                        access_token=access_token,
                        user_id=user_id,
                    )
            with suppress(Exception):
                await self._emby.stop_active_encodings(
                    play_session_id=play_session_id,
                    access_token=access_token,
                )

        self._tokens.revoke_party(party_id)
        with suppress(Exception):
            await self._sio.close_room(party_id)
        self._logger.info("Party dissolved: %s", party_id)
