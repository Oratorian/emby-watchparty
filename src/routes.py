"""
Flask Routes Module
All HTTP routes for the Emby Watch Party application
"""

from flask import render_template, request, jsonify, Response, session, redirect, url_for, Blueprint
from datetime import datetime
import requests
import re
from functools import wraps


def init_routes(app, emby_client, party_manager, config, logger, limiter=None):
    """
    Initialize all Flask routes with dependency injection

    Args:
        app: Flask application instance
        emby_client: EmbyClient instance
        party_manager: PartyManager instance
        config: Configuration module
        logger: Logger instance
        limiter: Optional Flask-Limiter instance
    """

    # Import utils functions
    from src.utils import (
        generate_random_username,
        generate_party_code,
        generate_hls_token,
        validate_hls_token,
        get_user_token,
    )

    # Quick access to state
    watch_parties = party_manager.watch_parties
    hls_tokens = party_manager.hls_tokens

    # Get APP_PREFIX for URL building
    app_prefix = getattr(config, 'APP_PREFIX', '')

    # Create a blueprint with the APP_PREFIX as url_prefix
    # This makes all routes respond at /prefix/route instead of /route
    bp = Blueprint(
        'main',
        __name__,
        url_prefix=app_prefix if app_prefix else None,
        static_folder='../static',
        static_url_path='/static'
    )

    # Helper function to build URLs with APP_PREFIX (for redirects)
    def prefixed_url(path):
        """Build URL with APP_PREFIX"""
        if app_prefix:
            return f"{app_prefix}{path}"
        return path

    # Authentication decorator
    def login_required(f):
        """Decorator to require login if REQUIRE_LOGIN is enabled"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            logger.info(f"[AUTH CHECK] REQUIRE_LOGIN={config.REQUIRE_LOGIN}, authenticated={'authenticated' in session}")
            if config.REQUIRE_LOGIN == 'true' and 'authenticated' not in session:
                logger.info(f"[AUTH CHECK] Redirecting to login page")
                return redirect(prefixed_url('/login'))
            logger.info(f"[AUTH CHECK] Access granted")
            return f(*args, **kwargs)
        return decorated_function

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
        return render_template("party.html", party_id=party_id, require_login=(config.REQUIRE_LOGIN == 'true'))

    # =============================================================================
    # Authentication Routes
    # =============================================================================

    @bp.route("/login")
    def login():
        """Login page"""
        # If login is not required, redirect to index
        if config.REQUIRE_LOGIN != 'true':
            return redirect(prefixed_url('/'))
        # If already authenticated, redirect to index
        if 'authenticated' in session:
            return redirect(prefixed_url('/'))
        return render_template("login.html")

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
                        session['access_token'] = access_token  # Store for potential future use
                        session.permanent = True

                        logger.info(f"User '{user_name}' logged in successfully")
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
            "require_login": config.REQUIRE_LOGIN == 'true'
        })

    # =============================================================================
    # API Routes
    # =============================================================================
    """
    REST API endpoints for building custom frontends.

    All endpoints return JSON unless otherwise specified.
    Rate limiting applies to some endpoints when ENABLE_RATE_LIMITING=true.

    Library & Media Endpoints:
        GET  /api/libraries           - List all Emby libraries
        GET  /api/items               - List items (with filters)
        GET  /api/search              - Search for content
        GET  /api/item/<id>           - Get item details
        GET  /api/item/<id>/streams   - Get audio/subtitle streams
        GET  /api/image/<id>          - Get item poster/thumbnail

    Party Management Endpoints:
        POST /api/party/create        - Create new watch party
        GET  /api/party/<id>/info     - Get party state

    HLS Streaming Endpoints (Token Protected):
        GET  /hls/<id>/master.m3u8    - HLS master playlist
        GET  /hls/<id>/<path>          - HLS segments/playlists
    """

    @bp.route("/api/libraries")
    def api_libraries():
        """
        Get all media libraries from Emby server.

        Returns:
            JSON: {
                "Items": [
                    {
                        "Id": str,
                        "Name": str,
                        "CollectionType": str ("movies", "tvshows", etc.)
                    }
                ]
            }

        Example:
            GET /api/libraries
        """
        libraries = emby_client.get_libraries()
        return jsonify(libraries)

    @bp.route("/api/items")
    def api_items():
        """
        Get items from a library (movies, series, episodes, seasons).

        Query Parameters:
            parentId (str, optional): Filter by parent library/series/season ID
            type (str, optional): Filter by type ("Movie", "Series", etc.)
            recursive (bool, optional): Include child items recursively

        Returns:
            JSON: {
                "Items": [
                    {
                        "Id": str,
                        "Name": str,
                        "Type": str,
                        "Overview": str,
                        "ProductionYear": int
                    }
                ]
            }

        Examples:
            GET /api/items?parentId=12345
            GET /api/items?type=Movie&recursive=true
        """
        parent_id = request.args.get("parentId")
        item_type = request.args.get("type")
        recursive = request.args.get("recursive", "false").lower() == "true"
        start_index = request.args.get("startIndex", type=int)
        limit = request.args.get("limit", type=int)

        items = emby_client.get_items(parent_id, item_type, recursive, start_index, limit)
        return jsonify(items)

    @bp.route("/api/search")
    def api_search():
        """
        Search for movies and TV series by name.

        Query Parameters:
            q (str, required): Search query string

        Returns:
            JSON: {
                "Items": [
                    {
                        "Id": str,
                        "Name": str,
                        "Type": str ("Movie" or "Series"),
                        "Overview": str,
                        "ProductionYear": int
                    }
                ]
            }

        Examples:
            GET /api/search?q=inception
            GET /api/search?q=breaking+bad
        """
        query = request.args.get("q", "").strip()

        if not query:
            return jsonify({"Items": []})

        results = emby_client.search_items(query)
        return jsonify(results)

    @bp.route("/api/item/<item_id>")
    def api_item_details(item_id):
        """
        Get detailed information for a specific item.

        Path Parameters:
            item_id (str): Emby item ID

        Returns:
            JSON: {
                "Id": str,
                "Name": str,
                "Type": str,
                "Overview": str,
                "ProductionYear": int,
                "MediaStreams": [...]
            }

        Errors:
            404: Item not found

        Example:
            GET /api/item/12345
        """
        details = emby_client.get_item_details(item_id)
        if details:
            return jsonify(details)
        return jsonify({"error": "Item not found"}), 404

    @bp.route("/api/item/<item_id>/streams")
    def api_item_streams(item_id):
        """
        Get available audio and subtitle streams for a media item.

        Path Parameters:
            item_id (str): Emby item ID

        Returns:
            JSON: {
                "audio": [
                    {
                        "index": int,
                        "language": str,
                        "displayLanguage": str,
                        "codec": str,
                        "channels": int,
                        "isDefault": bool,
                        "title": str
                    }
                ],
                "subtitles": [
                    {
                        "index": int,
                        "language": str,
                        "displayLanguage": str,
                        "codec": str,
                        "isDefault": bool,
                        "isForced": bool,
                        "isExternal": bool,
                        "title": str
                    }
                ]
            }

        Example:
            GET /api/item/<item_id>/streams
        """
        logger.debug(f"Fetching streams for item ID: {item_id}")

        # Try multiple approaches to get stream information
        playback_info = None

        # Method 1: Try PlaybackInfo endpoint
        playback_info = emby_client.get_playback_info(item_id)

        # Method 2: If that fails, try getting item details directly
        if not playback_info:
            playback_info = emby_client.get_item_details(item_id)

        # Method 3: Try using the streaming endpoint directly to infer info
        if not playback_info:
            logger.warning(
                f"Could not fetch item info via API, trying stream endpoint..."
            )
            try:
                # Make a HEAD request to the stream endpoint to see if it exists
                stream_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/stream.mp4?api_key={emby_client.api_key}"
                response = requests.head(stream_url, timeout=5)
                if response.status_code == 200:
                    logger.info(
                        f"Stream exists but no item metadata available - returning defaults"
                    )
                    # Return minimal stream info - just use defaults
                    return jsonify(
                        {
                            "audio": [],
                            "subtitles": [],
                            "note": "Stream info not available - using default settings",
                        }
                    )
            except Exception as e:
                logger.error(f"Stream endpoint check failed: {e}")

        if not playback_info:
            logger.error("All methods failed to get stream info")
            return (
                jsonify(
                    {
                        "error": "Could not fetch stream information",
                        "audio": [],
                        "subtitles": [],
                    }
                ),
                200,
            )

        audio_streams = []
        subtitle_streams = []
        media_source_id = None

        # Extract media streams - could be at different locations depending on endpoint
        media_streams = []

        # Check if we got PlaybackInfo response
        if "MediaSources" in playback_info and playback_info["MediaSources"]:
            media_streams = playback_info["MediaSources"][0].get("MediaStreams", [])
            media_source_id = playback_info["MediaSources"][0].get("Id")
        # Otherwise check for direct MediaStreams
        elif "MediaStreams" in playback_info:
            media_streams = playback_info["MediaStreams"]

        logger.debug(f"Found {len(media_streams)} media streams for item {item_id}")

        for stream in media_streams:
            stream_type = stream.get("Type")

            if stream_type == "Audio":
                lang = stream.get("Language", "und")
                display_lang = (
                    stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
                )
                if lang == "und":
                    display_lang = "Unknown"

                audio_streams.append(
                    {
                        "index": stream.get("Index"),
                        "language": lang,
                        "displayLanguage": display_lang,
                        "codec": stream.get("Codec", ""),
                        "channels": stream.get("Channels", 0),
                        "isDefault": stream.get("IsDefault", False),
                        "title": stream.get("Title", ""),
                    }
                )
            elif stream_type == "Subtitle":
                is_text_subtitle = stream.get("IsTextSubtitleStream", False)
                codec = stream.get("Codec", "").lower()

                # Detect image-based subtitle formats (PGS, VobSub)
                is_image_subtitle = codec in [
                    "pgssub",
                    "pgs",
                    "dvd_subtitle",
                    "dvdsub",
                    "vobsub",
                ]

                lang = stream.get("Language", "und")
                display_lang = (
                    stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
                )
                if lang == "und":
                    display_lang = "Unknown"

                subtitle_streams.append(
                    {
                        "index": stream.get("Index"),
                        "language": lang,
                        "displayLanguage": display_lang,
                        "codec": stream.get("Codec", ""),
                        "isDefault": stream.get("IsDefault", False),
                        "isForced": stream.get("IsForced", False),
                        "isExternal": stream.get("IsExternal", False),
                        "isTextSubtitleStream": is_text_subtitle,
                        "isPGS": is_image_subtitle,  # Mark image-based subs for burn-in
                        "title": stream.get("Title", ""),
                    }
                )

        logger.debug(
            f"Processed {len(audio_streams)} audio streams and {len(subtitle_streams)} subtitle streams"
        )

        return jsonify(
            {
                "audio": audio_streams,
                "subtitles": subtitle_streams,
                "media_source_id": media_source_id,
            }
        )

    @bp.route("/api/intro/<item_id>", methods=["GET"])
    def get_intro_info(item_id):
        """
        Get intro timing information for a specific item.

        Returns intro start/end times in seconds if available,
        or indicates no intro data exists.

        Response format:
            {
                "hasIntro": bool,
                "start": float (seconds),
                "end": float (seconds),
                "duration": float (seconds)
            }

        Example:
            GET /api/intro/63359
            Returns: {"hasIntro": true, "start": 90.67, "end": 138.56, "duration": 47.89}
        """
        logger.debug(f"Fetching intro info for item ID: {item_id}")

        try:
            # Fetch all intro data from Emby's Chapter API plugin
            # Note: This endpoint requires admin access, so we use API key directly
            response = requests.get(
                f"{config.EMBY_SERVER_URL}/emby/Items/Intros",
                params={"api_key": emby_client.api_key},
                headers={"Content-Type": "application/json"},
                timeout=5,
            )

            if response.status_code == 200:
                all_intros = response.json()

                # Find intro for this specific item
                for intro in all_intros:
                    if str(intro.get("Id")) == str(item_id):
                        # Convert ticks (100-nanosecond units) to seconds
                        # 1 second = 10,000,000 ticks
                        start_seconds = intro.get("Start", 0) / 10_000_000
                        end_seconds = intro.get("End", 0) / 10_000_000

                        logger.info(
                            f"Found intro for item {item_id}: {start_seconds:.2f}s - {end_seconds:.2f}s"
                        )

                        return jsonify(
                            {
                                "hasIntro": True,
                                "start": start_seconds,
                                "end": end_seconds,
                                "duration": end_seconds - start_seconds,
                            }
                        )

                # No intro found for this item
                logger.debug(f"No intro data found for item {item_id}")
                return jsonify({"hasIntro": False})
            else:
                logger.warning(
                    f"Failed to fetch intro data from Emby: HTTP {response.status_code}"
                )
                return jsonify({"hasIntro": False})

        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching intro info for item {item_id}")
            return jsonify({"hasIntro": False})
        except Exception as e:
            logger.error(f"Error fetching intro info for item {item_id}: {e}")
            return jsonify({"hasIntro": False})

    @bp.route("/hls/<item_id>/master.m3u8")
    def proxy_hls_master(item_id):
        """Lightweight HLS master playlist proxy - keeps Emby internal"""
        emby_url = None  # Initialize for error handling
        try:
            from flask import Response
            import re

            # Validate HLS token if enabled
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                token = request.args.get("token")
                logger.debug(
                    f"Master playlist request with token: {token[:16] if token else 'None'}... from {request.remote_addr}"
                )
                if not validate_hls_token(
                    token, hls_tokens, watch_parties, config, logger, item_id
                ):
                    logger.warning(
                        f"Invalid or missing HLS token for master playlist access from {request.remote_addr}"
                    )
                    return jsonify({"error": "Unauthorized"}), 401

            # Forward all query parameters from client (except our token)
            query_params = {k: v for k, v in request.args.items() if k != "token"}
            query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])

            # Build Emby URL
            emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/master.m3u8"
            if query_string:
                emby_url += f"?{query_string}"

            logger.debug(f"Proxying HLS master: {emby_url}")

            # Fetch from Emby (internal network only)
            emby_response = requests.get(emby_url, headers=emby_client.headers)
            emby_response.raise_for_status()
            logger.debug(
                f"Received master playlist from Emby, content length: {len(emby_response.text)} bytes"
            )
            logger.debug(f"Master playlist content:\n{emby_response.text}")

            # Rewrite URLs in the playlist to point to our proxy
            playlist_content = emby_response.text

            # Add token to rewritten URLs if validation is enabled
            token_param = (
                f"?token={request.args.get('token')}"
                if config.ENABLE_HLS_TOKEN_VALIDATION == 'true' and request.args.get("token")
                else ""
            )
            if token_param:
                logger.debug(f"Will add token parameter: {token_param[:30]}...")
            else:
                logger.debug("No token parameter (validation disabled or no token)")

            # Replace absolute Emby URLs with proxy URLs
            # Pattern: http://server/emby/Videos/ITEMID/path → /prefix/hls/ITEMID/path?token=...
            before_rewrite = playlist_content
            playlist_content = re.sub(
                rf"{re.escape(config.EMBY_SERVER_URL)}/emby/Videos/{item_id}/",
                f"{app_prefix}/hls/{item_id}/",
                playlist_content,
            )
            if before_rewrite != playlist_content:
                logger.debug("Rewrote absolute Emby URLs to proxy URLs")

            # Also handle relative URLs that might start with just the path
            # Pattern: /emby/Videos/ITEMID/path → /prefix/hls/ITEMID/path?token=...
            before_rewrite = playlist_content
            playlist_content = re.sub(
                rf"/emby/Videos/{item_id}/", f"{app_prefix}/hls/{item_id}/", playlist_content
            )
            if before_rewrite != playlist_content:
                logger.debug("Rewrote relative Emby URLs to proxy URLs")

            # Add token parameter to all segment URLs if needed
            if token_param:
                logger.debug(
                    f"Master playlist before token addition:\n{playlist_content}"
                )
                # Add token to .m3u8 and .ts file references
                # Match filenames ending with .m3u8 or .ts (not already having token param)
                lines = playlist_content.split("\n")
                for i, line in enumerate(lines):
                    # Skip comment lines and empty lines
                    if line.strip().startswith("#") or not line.strip():
                        continue
                    # If line contains .m3u8 or .ts and doesn't have token already
                    if (".m3u8" in line or ".ts" in line) and "token=" not in line:
                        # Use & if URL already has query params, otherwise use ?
                        separator = "&" if "?" in line else "?"
                        token_to_add = f"{separator}token={request.args.get('token')}"
                        old_line = line
                        lines[i] = line + token_to_add
                        logger.debug(f"Token addition: '{old_line}' -> '{lines[i]}'")
                playlist_content = "\n".join(lines)
                logger.debug(
                    f"Master playlist after token addition:\n{playlist_content}"
                )
            else:
                logger.debug("Skipping token addition (no token available)")

            logger.debug(
                f"Rewritten playlist URLs to use /hls/{item_id}/ prefix and added tokens"
            )

            # Return with CORS headers
            response = Response(
                playlist_content, mimetype="application/vnd.apple.mpegurl"
            )
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Range"

            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"CRITICAL: Failed to fetch master playlist from Emby server")
            logger.error(f"  Item ID: {item_id}")
            logger.error(
                f"  Emby URL: {emby_url if emby_url else '(URL not constructed)'}"
            )
            logger.error(f"  Error: {str(e)}")
            logger.error(f"  Error Type: {type(e).__name__}")
            return jsonify({"error": "Failed to fetch video from media server"}), 502
        except Exception as e:
            logger.error(f"CRITICAL: Unexpected error in HLS master playlist proxy")
            logger.error(f"  Item ID: {item_id}")
            logger.error(f"  Error: {str(e)}")
            logger.error(f"  Error Type: {type(e).__name__}")
            import traceback

            logger.error(f"  Traceback: {traceback.format_exc()}")
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/hls/<item_id>/<path:subpath>")
    def proxy_hls_segment(item_id, subpath):
        """Lightweight HLS segment/playlist proxy - keeps Emby internal"""
        emby_url = None  # Initialize for error handling
        try:
            from flask import Response
            import re

            # Validate HLS token if enabled
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                token = request.args.get("token")
                logger.debug(
                    f"Segment request for {subpath} with token: {token[:16] if token else 'None'}... from {request.remote_addr}"
                )
                if not validate_hls_token(
                    token, hls_tokens, watch_parties, config, logger, item_id
                ):
                    logger.warning(
                        f"Invalid or missing HLS token for segment access: {subpath} from {request.remote_addr}"
                    )
                    return jsonify({"error": "Unauthorized"}), 401

            # Forward all query parameters (except our token)
            query_params = {k: v for k, v in request.args.items() if k != "token"}
            query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])

            emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"
            if query_string:
                emby_url += f"?{query_string}"

            logger.debug(f"Proxying HLS segment: {subpath} -> {emby_url}")

            # Fetch from Emby (internal network only)
            emby_response = requests.get(
                emby_url, headers=emby_client.headers, stream=True
            )
            emby_response.raise_for_status()

            # Determine content type
            content_type = emby_response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            if subpath.endswith(".m3u8"):
                content_type = "application/vnd.apple.mpegurl"
            elif subpath.endswith(".ts"):
                content_type = "video/MP2T"

            # If this is a playlist (.m3u8), rewrite URLs
            if subpath.endswith(".m3u8"):
                playlist_content = emby_response.text

                # Add token to rewritten URLs if validation is enabled
                token_param = (
                    f"?token={request.args.get('token')}"
                    if config.ENABLE_HLS_TOKEN_VALIDATION == 'true' and request.args.get("token")
                    else ""
                )

                # Replace absolute Emby URLs with proxy URLs
                playlist_content = re.sub(
                    rf"{re.escape(config.EMBY_SERVER_URL)}/emby/Videos/{item_id}/",
                    f"{app_prefix}/hls/{item_id}/",
                    playlist_content,
                )

                # Also handle relative URLs
                playlist_content = re.sub(
                    rf"/emby/Videos/{item_id}/", f"{app_prefix}/hls/{item_id}/", playlist_content
                )

                # Add token parameter to segment URLs if needed
                if token_param:
                    # Add token to .m3u8 and .ts file references
                    lines = playlist_content.split("\n")
                    for i, line in enumerate(lines):
                        # Skip comment lines and empty lines
                        if line.strip().startswith("#") or not line.strip():
                            continue
                        # If line contains .m3u8 or .ts and doesn't have token already
                        if (".m3u8" in line or ".ts" in line) and "token=" not in line:
                            # Use & if URL already has query params, otherwise use ?
                            separator = "&" if "?" in line else "?"
                            token_to_add = (
                                f"{separator}token={request.args.get('token')}"
                            )
                            lines[i] = line + token_to_add
                    playlist_content = "\n".join(lines)

                response = Response(playlist_content, mimetype=content_type)
            else:

                def generate():
                    """Generator function to stream binary video segment data in chunks."""
                    for chunk in emby_response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk

                response = Response(generate(), mimetype=content_type)

                if "Content-Length" in emby_response.headers:
                    response.headers["Content-Length"] = emby_response.headers[
                        "Content-Length"
                    ]

            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Range"

            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"CRITICAL: Failed to fetch HLS segment from Emby server")
            logger.error(f"  Item ID: {item_id}")
            logger.error(f"  Subpath: {subpath}")
            logger.error(
                f"  Emby URL: {emby_url if emby_url else '(URL not constructed)'}"
            )
            logger.error(f"  Error: {str(e)}")
            logger.error(f"  Error Type: {type(e).__name__}")
            return (
                jsonify({"error": "Failed to fetch video segment from media server"}),
                502,
            )
        except Exception as e:
            logger.error(f"CRITICAL: Unexpected error in HLS segment proxy")
            logger.error(f"  Item ID: {item_id}")
            logger.error(f"  Subpath: {subpath}")
            logger.error(f"  Error: {str(e)}")
            logger.error(f"  Error Type: {type(e).__name__}")
            import traceback

            logger.error(f"  Traceback: {traceback.format_exc()}")
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/image/<item_id>")
    def api_image(item_id):
        """
        Get poster/thumbnail image for a media item.

        Proxies image requests from Emby server to keep server internal.

        Path Parameters:
            item_id (str): Emby item ID

        Query Parameters:
            type (str, optional): Image type (default: "Primary")
                Options: "Primary", "Backdrop", "Thumb", etc.

        Returns:
            Binary image data (JPEG/PNG)

        Errors:
            404: Image not found

        Example:
            GET /api/image/12345?type=Primary
        """
        image_type = request.args.get("type", "Primary")
        image_url = emby_client.get_image_url(item_id, image_type)

        try:
            response = requests.get(image_url, headers=emby_client.headers)
            if response.status_code == 200:
                return (
                    response.content,
                    200,
                    {
                        "Content-Type": response.headers.get(
                            "Content-Type", "image/jpeg"
                        )
                    },
                )
            else:
                return "", 404
        except Exception as e:
            logger.error(f"Error fetching image: {e}")
            return "", 404

    @bp.route("/api/subtitles/<item_id>/<media_source_id>/<int:subtitle_index>")
    def api_subtitles(item_id, media_source_id, subtitle_index):
        """
        Get subtitle file for a media item in WebVTT format.

        Proxies subtitle requests from Emby server to keep server internal.

        Path Parameters:
            item_id (str): Emby item ID
            media_source_id (str): Media source ID
            subtitle_index (int): Subtitle stream index

        Returns:
            WebVTT subtitle file (text/vtt)

        Errors:
            404: Subtitle not found

        Example:
            GET /api/subtitles/12345/67890/2
        """
        try:
            # Build Emby subtitle URL (always request VTT format for web compatibility)
            subtitle_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{media_source_id}/Subtitles/{subtitle_index}/Stream.vtt"

            # Add API key
            subtitle_url += f"?api_key={emby_client.api_key}"

            logger.debug(f"Fetching subtitle: {subtitle_url}")

            response = requests.get(subtitle_url, headers=emby_client.headers)
            if response.status_code == 200:
                return (
                    response.content,
                    200,
                    {"Content-Type": "text/vtt", "Access-Control-Allow-Origin": "*"},
                )
            else:
                logger.warning(
                    f"Subtitle not found: {subtitle_url} (status: {response.status_code})"
                )
                return "", 404
        except Exception as e:
            logger.error(f"Error fetching subtitle: {e}")
            return "", 404

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
        party_id = generate_party_code(watch_parties)

        watch_parties[party_id] = {
            "id": party_id,
            "created_at": datetime.now().isoformat(),
            "users": {},
            "current_video": None,
            "playback_state": {
                "playing": False,
                "time": 0,
                "last_update": datetime.now().isoformat(),
            },
        }

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

    # =============================================================================
    # WebSocket Events
    # =============================================================================
    """
    Socket.IO events for real-time party synchronization.

    Connection Events:
        connect              - Client connects to server
        disconnect           - Client disconnects

    Party Management Events:
        join_party           - Join a watch party room
            Data: {party_id, username}
        leave_party          - Leave a watch party room
            Data: {party_id}

    Video Control Events (Synced to all users):
        select_video         - Select a video to watch
            Data: {party_id, item_id, item_name, item_overview}
        play                 - Play video
            Data: {party_id, time}
        pause                - Pause video
            Data: {party_id, time}
        seek                 - Seek to position
            Data: {party_id, time, playing}
        change_streams       - Change audio/subtitle tracks
            Data: {party_id, audio_index, subtitle_index}

    Chat Events:
        chat_message         - Send chat message
            Data: {party_id, message}

    Server Emitted Events:
        connected            - Connection confirmed
        user_joined          - User joined party
        user_left            - User left party
        sync_state           - Initial party state on join
        video_selected       - New video selected
        streams_changed      - Audio/subtitle changed
        play                 - Play command
        pause                - Pause command
        seek                 - Seek command
        chat_message         - Chat message broadcast
        error                - Error message
    """

    # Register the blueprint with the app
    app.register_blueprint(bp)
