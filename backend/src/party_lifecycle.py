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
        self._limiter = ctx.get("rate_limiter")
        self._logger = ctx["logger"]
        self._pending_empty: dict[str, asyncio.Task] = {}

    def cancel_empty_dissolution(self, party_id: str) -> None:
        task = self._pending_empty.pop(party_id, None)
        if task is not None and not task.done():
            task.cancel()

    def schedule_empty_dissolution(self, party_id: str, *, delay: float) -> None:
        self.cancel_empty_dissolution(party_id)

        async def dissolve_after_grace() -> None:
            try:
                await asyncio.sleep(delay)
                await self.dissolve_if_empty(party_id)
            except asyncio.CancelledError:
                return
            finally:
                current = asyncio.current_task()
                if self._pending_empty.get(party_id) is current:
                    self._pending_empty.pop(party_id, None)

        self._pending_empty[party_id] = asyncio.create_task(
            dissolve_after_grace(),
            name=f"empty-party-grace:{party_id}",
        )

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
        pending = list(self._pending_empty.values())
        self._pending_empty.clear()
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
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
            self._pending_empty.pop(party_id, None),
        ):
            if isinstance(task, asyncio.Task) and task is not current and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        video = party.current_video
        access_token = party.host_access_token
        user_id = party.host_user_id
        position = party.playback_state.time
        for stream in list((party.user_streams or {}).values()):
            play_session_id = stream.play_session_id
            if not play_session_id:
                continue
            if video:
                with suppress(Exception):
                    await self._emby.report_playback_stopped(
                        item_id=video.item_id,
                        media_source_id=stream.media_source_id,
                        play_session_id=play_session_id,
                        position_seconds=position,
                        run_time_seconds=video.run_time_seconds,
                        access_token=access_token,
                        user_id=user_id,
                    )
            with suppress(Exception):
                await self._emby.stop_active_encodings(
                    play_session_id=play_session_id,
                    access_token=access_token,
                )

        revoked_tokens = self._tokens.revoke_party(party_id)
        cleared_limiters = 0
        if self._limiter is not None:
            for sid in party.sids():
                cleared_limiters += self._limiter.clear_prefix(f"chat:{sid}")
        with suppress(Exception):
            await self._sio.close_room(party_id)
        self._logger.info(
            "cleanup party=%s outcome=ok task_cleanup=%s "
            "transcode_cleanup=%s token_cleanup=%s limiter_cleanup=%s",
            party_id,
            len(tasks),
            sum(1 for stream in party.user_streams.values() if stream.play_session_id),
            revoked_tokens,
            cleared_limiters,
        )
