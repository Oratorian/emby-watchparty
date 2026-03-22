"""
Auth Routes - Login, logout, version, authentication status
Routes: /login, /version, /api/version, /api/auth/login, /api/auth/logout, /api/auth/status
"""

from flask import render_template, request, jsonify, session, redirect
import requests


def register(deps):
    bp = deps['bp']
    emby_client = deps['emby_client']
    config = deps['config']
    logger = deps['logger']
    prefixed_url = deps['prefixed_url']
    login_required = deps['login_required']

    @bp.route("/login")
    def login():
        """Login page"""
        # If login is not required, redirect to index
        if not config.REQUIRE_LOGIN:
            return redirect(prefixed_url('/'))
        # If already authenticated, redirect to index
        if 'authenticated' in session:
            return redirect(prefixed_url('/'))
        return render_template("login.html")

    @bp.route("/version")
    @login_required
    def version():
        """Version and about page"""
        from src import __version__, __codename__
        return render_template("version.html",
                               current_version=__version__,
                               codename=__codename__,
                               require_login=(config.REQUIRE_LOGIN))

    @bp.route("/api/version")
    @login_required
    def api_version():
        """Check current version and available updates"""
        from src import __version__, __codename__
        result = {
            "current_version": __version__,
            "codename": __codename__,
            "latest_version": None,
            "update_available": False,
            "release_url": None
        }
        try:
            github_api_url = "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
            response = requests.get(github_api_url, timeout=5)
            if response.status_code == 200:
                release = response.json()
                latest = release.get("tag_name", "").lstrip("v")
                result["latest_version"] = latest
                result["update_available"] = bool(latest and latest != __version__)
                result["release_url"] = release.get("html_url")
        except Exception:
            pass
        return jsonify(result)

    @bp.route("/api/auth/login", methods=["POST"])
    def api_login():
        """
        Authenticate user with Emby credentials.

        POST body: {"username": str, "password": str}

        Returns:
            JSON: {"success": bool, "message": str, "username": str (optional)}
        """
        try:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')

            if not username or not password:
                return jsonify({"success": False, "message": "Username and password are required"}), 400

            # Create temporary EmbyClient to authenticate
            temp_client = type('obj', (object,), {
                'server_url': emby_client.server_url,
                'api_key': emby_client.api_key,
                'logger': logger,
                'device_id': emby_client.device_id
            })()

            # Try to authenticate
            try:
                url = f"{emby_client.server_url}/emby/Users/AuthenticateByName"
                headers = {
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": f'Emby Client="WatchParty", Device="Web", DeviceId="{emby_client.device_id}", Version="1.0"',
                }
                payload = {"Username": username, "Pw": password}

                logger.debug(f"Attempting authentication for '{username}' at: {url}")
                response = requests.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    access_token = data.get("AccessToken")
                    user_name = data.get("User", {}).get("Name", username)

                    if access_token:
                        # Store session data
                        session['authenticated'] = True
                        session['username'] = user_name
                        session['access_token'] = access_token
                        session['is_admin'] = data.get("User", {}).get("Policy", {}).get("IsAdministrator", False)
                        session.permanent = True

                        logger.info(f"User '{user_name}' logged in successfully (admin={session['is_admin']})")
                        return jsonify({"success": True, "message": "Login successful", "username": user_name})
                    else:
                        logger.warning(f"Login attempt for '{username}' - no access token returned")
                        return jsonify({"success": False, "message": "Authentication failed"}), 401
                else:
                    error_text = response.text
                    logger.warning(f"Login attempt for '{username}' failed: {error_text}")
                    return jsonify({"success": False, "message": error_text or "Invalid username or password"}), 401

            except requests.exceptions.Timeout:
                logger.error(f"Login timeout for user '{username}'")
                return jsonify({"success": False, "message": "Connection to Emby server timed out"}), 504
            except requests.exceptions.RequestException as e:
                logger.error(f"Login request error for '{username}': {e}")
                return jsonify({"success": False, "message": "Unable to connect to Emby server"}), 502

        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({"success": False, "message": "Internal server error"}), 500

    @bp.route("/api/auth/logout", methods=["POST"])
    def api_logout():
        """
        Logout current user.

        Returns:
            JSON: {"success": bool, "message": str}
        """
        username = session.get('username', 'Unknown')
        session.clear()
        logger.info(f"User '{username}' logged out")
        return jsonify({"success": True, "message": "Logged out successfully"})

    @bp.route("/api/auth/status")
    def api_auth_status():
        """
        Check authentication status.

        Returns:
            JSON: {"authenticated": bool, "username": str (optional), "require_login": bool}
        """
        return jsonify({
            "authenticated": 'authenticated' in session,
            "username": session.get('username'),
            "require_login": config.REQUIRE_LOGIN
        })
