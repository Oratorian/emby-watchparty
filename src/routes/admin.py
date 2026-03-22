"""
Admin Routes - Settings management panel
Routes: /admin, /api/admin/config
Requires Emby administrator account (IsAdministrator policy)
"""

import logging
from flask import render_template, request, jsonify, session, redirect
from functools import wraps


def register(deps):
    bp = deps['bp']
    config = deps['config']
    logger = deps['logger']
    prefixed_url = deps['prefixed_url']

    def admin_required(f):
        """Protect admin routes -- require Emby admin when login is enabled, open otherwise"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if config.REQUIRE_LOGIN:
                if 'authenticated' not in session:
                    return redirect(prefixed_url('/login'))
                if not session.get('is_admin', False):
                    return jsonify({"error": "Administrator access required"}), 403
            return f(*args, **kwargs)
        return decorated

    @bp.route("/admin")
    @admin_required
    def admin_panel():
        """Render the admin settings panel"""
        from src import __version__, __codename__
        return render_template(
            "admin.html",
            current_version=__version__,
            codename=__codename__,
            require_login=config.REQUIRE_LOGIN,
        )

    @bp.route("/api/admin/config", methods=["GET"])
    @admin_required
    def get_config():
        """Get current runtime configuration"""
        return jsonify(config.get_runtime_dict())

    @bp.route("/api/admin/config", methods=["PUT"])
    @admin_required
    def update_config():
        """
        Update runtime configuration settings.

        Accepts a JSON object with setting key/value pairs.
        Only RuntimeConfig fields are accepted; EnvConfig fields are rejected.
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Reject any env-only settings
        env_only = {
            'WATCH_PARTY_BIND', 'WATCH_PARTY_PORT', 'APP_PREFIX',
            'REQUIRE_LOGIN', 'SESSION_EXPIRY',
            'EMBY_SERVER_URL', 'EMBY_API_KEY', 'EMBY_USERNAME', 'EMBY_PASSWORD',
        }
        rejected = [k for k in data.keys() if k in env_only]
        if rejected:
            return jsonify({
                "error": f"These settings can only be changed in .env (restart required): {', '.join(rejected)}"
            }), 400

        try:
            changed = config.update_runtime(data)

            # Hot-reload logging if log settings changed
            log_fields = {'LOG_LEVEL', 'CONSOLE_LOG_LEVEL'}
            if log_fields & set(changed):
                _reload_log_levels(config, logger)

            logger.info(f"Admin config updated: {changed}")
            return jsonify({
                "success": True,
                "changed": changed,
                "config": config.get_runtime_dict(),
            })
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return jsonify({"error": str(e)}), 500


def _reload_log_levels(config, logger):
    """Hot-reload log levels for all application loggers"""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    console_level = getattr(logging, config.CONSOLE_LOG_LEVEL.upper(), logging.WARNING)

    for name in ['emby-watchparty', 'socketio', 'werkzeug']:
        lg = logging.getLogger(name)
        lg.setLevel(level)
        for handler in lg.handlers:
            if hasattr(handler, 'stream') and hasattr(handler.stream, 'isatty'):
                handler.setLevel(console_level)
            else:
                handler.setLevel(level)

    logger.info(f"Log levels reloaded: app={config.LOG_LEVEL}, console={config.CONSOLE_LOG_LEVEL}")
