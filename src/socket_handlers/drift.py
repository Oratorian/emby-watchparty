"""
Drift Correction Handler
Events: heartbeat -> drift_correction
Clients send their playback position periodically. Server compares against
expected position and sends targeted corrections to drifted clients only.
"""

from flask_socketio import emit
from flask import request
from datetime import datetime

DRIFT_THRESHOLD = 3.0       # seconds of drift before considered out of sync
CONSECUTIVE_REQUIRED = 2    # consecutive drifted heartbeats before correction


def register(deps):
    socketio = deps['socketio']
    logger = deps['logger']
    watch_parties = deps['watch_parties']

    @socketio.on("heartbeat")
    def handle_heartbeat(data):
        """Compare client position against expected and correct if drifted"""
        party_id = data.get("party_id", "").strip().upper()
        client_time = data.get("time", 0)

        if party_id not in watch_parties:
            return

        party = watch_parties[party_id]

        # Skip if no video or not playing
        if not party.get("current_video"):
            return

        playback_state = party.get("playback_state", {})
        if not playback_state.get("playing"):
            return

        # Calculate expected position
        last_update = playback_state.get("last_update")
        if not last_update:
            return

        try:
            last_update_dt = datetime.fromisoformat(last_update)
            elapsed = (datetime.now() - last_update_dt).total_seconds()
            expected_time = playback_state["time"] + elapsed
        except (ValueError, KeyError):
            return

        drift = abs(client_time - expected_time)
        username = party["users"].get(request.sid, "Unknown")
        logger.debug(
            f"Heartbeat from {username}: client={client_time:.1f}s, "
            f"expected={expected_time:.1f}s, drift={drift:.1f}s"
        )

        # Track consecutive drift per client
        drift_strikes = party.setdefault("drift_strikes", {})

        if drift > DRIFT_THRESHOLD:
            drift_strikes[request.sid] = drift_strikes.get(request.sid, 0) + 1
        else:
            drift_strikes[request.sid] = 0
            return

        # Only correct after consecutive drifted heartbeats
        if drift_strikes[request.sid] >= CONSECUTIVE_REQUIRED:
            username = party["users"].get(request.sid, "Unknown")
            logger.info(
                f"Drift correction sent to {username}: "
                f"drift={drift:.1f}s, client={client_time:.1f}s, expected={expected_time:.1f}s"
            )
            emit("drift_correction", {"time": expected_time}, to=request.sid)
            drift_strikes[request.sid] = 0
