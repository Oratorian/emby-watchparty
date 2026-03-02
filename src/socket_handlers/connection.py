"""
Connection Handlers
Events: connect, disconnect
"""

from flask_socketio import emit
from flask import request


def register(deps):
    socketio = deps['socketio']
    logger = deps['logger']
    watch_parties = deps['watch_parties']

    @socketio.on("connect")
    def handle_connect():
        """Handle new WebSocket connection"""
        logger.info(f"Client connected: {request.sid}")
        emit("connected", {"sid": request.sid})

    @socketio.on("disconnect")
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        logger.info(f"Client disconnected: {request.sid}")

        # Remove user from all watch parties
        for party_id, party in watch_parties.items():
            if request.sid in party["users"]:
                username = party["users"][request.sid]
                del party["users"][request.sid]
                emit(
                    "user_left",
                    {"username": username, "users": list(party["users"].values())},
                    room=party_id,
                    skip_sid=request.sid,
                )
