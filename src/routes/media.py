"""
Media Routes - Intro info, images, subtitles
Routes: /api/intro/<id>, /api/image/<id>, /api/subtitles/<id>/<msid>/<idx>
"""

from flask import request, jsonify, Response
import requests


def register(deps):
    bp = deps['bp']
    emby_client = deps['emby_client']
    config = deps['config']
    logger = deps['logger']

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
            emby_resp = requests.get(image_url, headers=emby_client.headers)
            if emby_resp.status_code == 200:
                # Whitelist Content-Type to image types only
                upstream_ct = emby_resp.headers.get("Content-Type", "image/jpeg")
                if not upstream_ct.startswith("image/"):
                    upstream_ct = "image/jpeg"
                resp = Response(emby_resp.content, mimetype=upstream_ct)
                resp.headers["X-Content-Type-Options"] = "nosniff"
                return resp
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

            emby_resp = requests.get(subtitle_url, headers=emby_client.headers)
            if emby_resp.status_code == 200:
                resp = Response(emby_resp.content, mimetype="text/vtt")
                resp.headers["Access-Control-Allow-Origin"] = "*"
                resp.headers["X-Content-Type-Options"] = "nosniff"
                return resp
            else:
                logger.warning(
                    f"Subtitle not found: {subtitle_url} (status: {emby_resp.status_code})"
                )
                return "", 404
        except Exception as e:
            logger.error(f"Error fetching subtitle: {e}")
            return "", 404
