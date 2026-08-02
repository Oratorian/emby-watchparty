"""Drift correction handler: heartbeat"""

from datetime import UTC, datetime

DRIFT_THRESHOLD = 3.0
CONSECUTIVE_REQUIRED = 2


def register(ctx):
    sio = ctx["sio"]
    logger = ctx["logger"]
    party_manager = ctx["party_manager"]

    @sio.on("heartbeat")
    async def handle_heartbeat(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        client_time = data.get("time", 0)
        party = party_manager.get(party_id)

        if not party or not party.current_video:
            return

        playback_state = party.playback_state
        if not playback_state.playing:
            return

        last_update = playback_state.last_update
        if not last_update:
            return

        try:
            last_update_dt = datetime.fromisoformat(last_update)
            elapsed = (datetime.now(UTC) - last_update_dt).total_seconds()
            expected_time = playback_state.time + elapsed
        except (ValueError, KeyError):
            return

        drift = abs(client_time - expected_time)
        username = party.username_for_sid(sid)
        logger.debug(
            f"Heartbeat from {username}: client={client_time:.1f}s, "
            f"expected={expected_time:.1f}s, drift={drift:.1f}s"
        )

        drift_strikes = party.drift_strikes

        if drift > DRIFT_THRESHOLD:
            drift_strikes[sid] = drift_strikes.get(sid, 0) + 1
        else:
            drift_strikes[sid] = 0
            return

        if drift_strikes[sid] >= CONSECUTIVE_REQUIRED:
            logger.info(
                f"Drift correction sent to {username}: "
                f"drift={drift:.1f}s, client={client_time:.1f}s, expected={expected_time:.1f}s"
            )
            await sio.emit("drift_correction", {"time": expected_time}, to=sid)
            drift_strikes[sid] = 0
