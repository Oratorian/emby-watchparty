"""
Party API Routes - Party creation and info
Routes: /api/party/create, /api/party/<id>/info
"""

from flask import jsonify
from datetime import datetime


def register(deps):
    bp = deps['bp']
    logger = deps['logger']
    config = deps['config']
    limiter = deps['limiter']
    party_manager = deps['party_manager']
    watch_parties = deps['watch_parties']
    prefixed_url = deps['prefixed_url']

    @bp.route("/api/party/create", methods=["POST"])
    def create_party():
        """
        Create a new watch party room.

        Method: POST

        Returns:
            JSON: {
                "party_id": str (unique party identifier),
                "url": str (party URL path)
            }

        Rate Limit:
            5 per hour per IP (if rate limiting enabled)

        Example:
            POST /api/party/create
            Response: {"party_id": "A3B7K", "url": "/party/A3B7K"}
        """
        party_id = party_manager.create_party()
        logger.info(f"Created new watch party: {party_id}")
        return jsonify({"party_id": party_id, "url": prefixed_url(f"/party/{party_id}")})

    # Apply rate limiting to party creation if enabled
    if limiter:
        create_party = limiter.limit(config.RATE_LIMIT_PARTY_CREATION)(create_party)

    @bp.route("/api/party/<party_id>/info")
    def party_info(party_id):
        """
        Get current state and information about a watch party.

        Path Parameters:
            party_id (str): Party ID

        Returns:
            JSON: {
                "id": str,
                "users": [str] (list of usernames),
                "current_video": {
                    "item_id": str,
                    "title": str,
                    "overview": str,
                    "stream_url_base": str,
                    "audio_index": int,
                    "subtitle_index": int
                } or null,
                "playback_state": {
                    "playing": bool,
                    "time": float,
                    "last_update": str (ISO timestamp)
                }
            }

        Errors:
            404: Party not found

        Example:
            GET /api/party/abc123/info
        """
        if party_id not in watch_parties:
            return jsonify({"error": "Party not found"}), 404

        party = watch_parties[party_id]
        return jsonify(
            {
                "id": party["id"],
                "users": list(party["users"].values()),
                "current_video": party["current_video"],
                "playback_state": party["playback_state"],
            }
        )
