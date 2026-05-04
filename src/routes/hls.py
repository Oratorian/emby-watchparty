"""
HLS Routes - HLS playlist and segment proxying
Routes: /hls/<id>/master.m3u8, /hls/<id>/<path:subpath>
"""

from flask import request, jsonify, Response
import requests
import re


def register(deps):
    bp = deps['bp']
    emby_client = deps['emby_client']
    config = deps['config']
    logger = deps['logger']
    validate_hls_token = deps['validate_hls_token']
    hls_tokens = deps['hls_tokens']
    watch_parties = deps['watch_parties']
    app_prefix = deps['app_prefix']

    @bp.route("/hls/<item_id>/master.m3u8")
    def proxy_hls_master(item_id):
        """Lightweight HLS master playlist proxy - keeps Emby internal"""
        emby_url = None  # Initialize for error handling
        try:
            # Validate HLS token if enabled
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                token = request.args.get("token")
                logger.info(
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
            # Pattern: http://server/emby/Videos/ITEMID/path -> /prefix/hls/ITEMID/path?token=...
            before_rewrite = playlist_content
            escaped_id = re.escape(item_id)
            playlist_content = re.sub(
                rf"{re.escape(config.EMBY_SERVER_URL)}/emby/Videos/{escaped_id}/",
                f"{app_prefix}/hls/{item_id}/",
                playlist_content,
            )
            if before_rewrite != playlist_content:
                logger.debug("Rewrote absolute Emby URLs to proxy URLs")

            # Also handle relative URLs that might start with just the path
            # Pattern: /emby/Videos/ITEMID/path -> /prefix/hls/ITEMID/path?token=...
            before_rewrite = playlist_content
            playlist_content = re.sub(
                rf"/emby/Videos/{escaped_id}/", f"{app_prefix}/hls/{item_id}/", playlist_content
            )
            if before_rewrite != playlist_content:
                logger.debug("Rewrote relative Emby URLs to proxy URLs")

            # Add token parameter to all segment URLs if needed
            if token_param:
                logger.debug(
                    f"Master playlist before token addition:\n{playlist_content}"
                )
                token_value = request.args.get('token')
                lines = playlist_content.split("\n")
                for i, line in enumerate(lines):
                    if not line.strip():
                        continue
                    # #EXT-X-MEDIA lines (used by Emby for SubtitleMethod=Hls
                    # text-subtitle tracks) carry the playlist URL inside a
                    # URI="..." attribute. The plain-line branch skips comments
                    # so the subtitle .m3u8 URI never gets the token, and
                    # HLS.js requests it without auth (issue #29 follow-up).
                    if line.strip().startswith("#EXT-X-MEDIA") and "URI=\"" in line:
                        old_line = line
                        def _add_token(m):
                            uri = m.group(1)
                            if "token=" in uri:
                                return m.group(0)
                            sep = "&" if "?" in uri else "?"
                            return f'URI="{uri}{sep}token={token_value}"'
                        lines[i] = re.sub(r'URI="([^"]+)"', _add_token, line)
                        if lines[i] != old_line:
                            logger.debug(f"Subtitle URI token addition: '{old_line}' -> '{lines[i]}'")
                        continue
                    # Skip other comment lines.
                    if line.strip().startswith("#"):
                        continue
                    # Plain URL lines: any non-comment, non-empty line in
                    # an HLS playlist is a media URL by spec. Append the
                    # token unconditionally rather than gating on extension,
                    # since Emby can serve subtitle segments as .vtt, .srt,
                    # .ass, or other formats depending on source and version.
                    if "token=" not in line:
                        separator = "&" if "?" in line else "?"
                        token_to_add = f"{separator}token={token_value}"
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
            response.headers["X-Content-Type-Options"] = "nosniff"

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
                escaped_id = re.escape(item_id)
                playlist_content = re.sub(
                    rf"{re.escape(config.EMBY_SERVER_URL)}/emby/Videos/{escaped_id}/",
                    f"{app_prefix}/hls/{item_id}/",
                    playlist_content,
                )

                # Also handle relative URLs
                playlist_content = re.sub(
                    rf"/emby/Videos/{escaped_id}/", f"{app_prefix}/hls/{item_id}/", playlist_content
                )

                # Add token parameter to segment URLs if needed
                if token_param:
                    token_value = request.args.get('token')
                    lines = playlist_content.split("\n")
                    for i, line in enumerate(lines):
                        if not line.strip():
                            continue
                        # #EXT-X-MEDIA URI attribute (rare in sub-playlists
                        # but covered for completeness).
                        if line.strip().startswith("#EXT-X-MEDIA") and "URI=\"" in line:
                            def _add_token(m):
                                uri = m.group(1)
                                if "token=" in uri:
                                    return m.group(0)
                                sep = "&" if "?" in uri else "?"
                                return f'URI="{uri}{sep}token={token_value}"'
                            lines[i] = re.sub(r'URI="([^"]+)"', _add_token, line)
                            continue
                        if line.strip().startswith("#"):
                            continue
                        # Plain URL lines: any non-comment line is a media URL
                        # per HLS spec. Append unconditionally rather than
                        # gating on extension since subtitle segments can
                        # be .vtt, .srt, .ass, etc.
                        if "token=" not in line:
                            separator = "&" if "?" in line else "?"
                            token_to_add = f"{separator}token={token_value}"
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
            response.headers["X-Content-Type-Options"] = "nosniff"

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
