"""
Admin Routes - Settings management panel
Routes: /admin, /admin/login, /api/admin/login, /api/admin/config
Always requires Emby administrator credentials (IsAdministrator policy)
"""

import logging
import requests as http_requests
from flask import render_template, request, jsonify, session, redirect
from functools import wraps


def register(deps):
    bp = deps['bp']
    config = deps['config']
    emby_client = deps['emby_client']
    logger = deps['logger']
    prefixed_url = deps['prefixed_url']

    def admin_required(f):
        """Always require authenticated Emby administrator"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('admin_authenticated', False):
                return redirect(prefixed_url('/admin/login'))
            return f(*args, **kwargs)
        return decorated

    @bp.route("/admin/login", methods=["GET"])
    def admin_login_page():
        """Admin login page"""
        if session.get('admin_authenticated'):
            return redirect(prefixed_url('/admin'))
        from src import __version__, __codename__
        return render_template(
            "admin_login.html",
            current_version=__version__,
            codename=__codename__,
        )

    @bp.route("/api/admin/login", methods=["POST"])
    def admin_login():
        """Authenticate with Emby and verify IsAdministrator"""
        data = request.get_json()
        username = (data or {}).get('username', '')
        password = (data or {}).get('password', '')

        if not username or not password:
            return jsonify({"success": False, "message": "Username and password are required"}), 400

        try:
            url = f"{emby_client.server_url}/emby/Users/AuthenticateByName"
            headers = {
                "Content-Type": "application/json",
                "X-Emby-Authorization": f'Emby Client="WatchParty", Device="Web", DeviceId="{emby_client.device_id}", Version="1.0"',
            }
            resp = http_requests.post(url, headers=headers, json={"Username": username, "Pw": password}, timeout=15)

            if resp.status_code != 200:
                return jsonify({"success": False, "message": "Invalid credentials"}), 401

            auth_data = resp.json()
            is_admin = auth_data.get("User", {}).get("Policy", {}).get("IsAdministrator", False)

            if not is_admin:
                logger.warning(f"Admin login denied for '{username}' -- not an Emby administrator")
                return jsonify({"success": False, "message": "This account does not have administrator privileges"}), 403

            session['admin_authenticated'] = True
            session['admin_username'] = auth_data.get("User", {}).get("Name", username)
            logger.info(f"Admin login: '{session['admin_username']}'")
            return jsonify({"success": True})

        except http_requests.exceptions.Timeout:
            return jsonify({"success": False, "message": "Emby server connection timed out"}), 504
        except http_requests.exceptions.RequestException as e:
            logger.error(f"Admin login error: {e}")
            return jsonify({"success": False, "message": "Unable to connect to Emby server"}), 502

    @bp.route("/api/admin/logout", methods=["POST"])
    def admin_logout():
        """Logout from admin panel"""
        session.pop('admin_authenticated', None)
        session.pop('admin_username', None)
        return jsonify({"success": True})

    @bp.route("/admin")
    @admin_required
    def admin_panel():
        """Render the admin settings panel"""
        from src import __version__, __codename__
        return render_template(
            "admin.html",
            current_version=__version__,
            codename=__codename__,
            admin_username=session.get('admin_username', 'Admin'),
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
