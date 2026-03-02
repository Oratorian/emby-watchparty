"""
Chat and UI Handlers
Events: chat_message, toggle_library
"""

from flask_socketio import emit
from flask import request
from datetime import datetime


def register(deps):
    socketio = deps['socketio']
    logger = deps['logger']
    watch_parties = deps['watch_parties']

    @socketio.on("chat_message")
    def handle_chat_message(data):
        """Handle chat messages"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        message = data.get("message", "")

        if (
            party_id in watch_parties
            and request.sid in watch_parties[party_id]["users"]
        ):
            username = watch_parties[party_id]["users"][request.sid]

            emit(
                "chat_message",
                {
                    "username": username,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                },
                room=party_id,
            )

    @socketio.on("toggle_library")
    def handle_toggle_library(data):
        """Handle library sidebar toggle for all users"""
        party_id = data.get("party_id", "").strip().upper()
        show = data.get("show", False)

        if party_id in watch_parties:
            logger.info(f"Library toggled in party {party_id}: show={show}")

            # Broadcast to all users in the party
            emit("toggle_library", {"show": show}, room=party_id)
