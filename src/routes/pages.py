"""
Page Routes - HTML page rendering
Routes: /, /party/<party_id>
"""

from flask import render_template, redirect
from datetime import datetime


def register(deps):
    bp = deps['bp']
    config = deps['config']
    logger = deps['logger']
    watch_parties = deps['watch_parties']
    prefixed_url = deps['prefixed_url']
    login_required = deps['login_required']

    @bp.route("/")
    @login_required
    def index():
        """Main page - choose to create or join a watch party"""
        # Static session mode: redirect straight to the persistent party
        if config.STATIC_SESSION_ENABLED == 'true':
            return redirect(prefixed_url(f'/party/{config.STATIC_SESSION_ID}'))
        return render_template("index.html", require_login=(config.REQUIRE_LOGIN == 'true'))

    @bp.route("/party/<party_id>")
    @login_required
    def party(party_id):
        """Watch party room page"""
        # Convert to uppercase for case-insensitive matching
        party_id = party_id.upper()

        if party_id not in watch_parties:
            # Recreate static party if it was somehow deleted
            if config.STATIC_SESSION_ENABLED == 'true' and party_id == config.STATIC_SESSION_ID:
                watch_parties[party_id] = {
                    "id": party_id,
                    "created_at": datetime.now().isoformat(),
                    "host_name": None,
                    "users": {},
                    "current_video": None,
                    "playback_state": {
                        "playing": False,
                        "time": 0,
                        "last_update": datetime.now().isoformat(),
                    },
                }
                logger.info(f"Recreated static party: {party_id}")
            else:
                return (
                    render_template(
                        "error.html",
                        party_id=party_id,
                        message="The watch party you're looking for doesn't exist or has ended.",
                    ),
                    404,
                )
        from src import __version__, __codename__
        return render_template("party.html", party_id=party_id, require_login=(config.REQUIRE_LOGIN == 'true'), current_version=__version__, codename=__codename__)
