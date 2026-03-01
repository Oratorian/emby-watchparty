"""
Library Routes - Emby library browsing and search
Routes: /api/libraries, /api/items, /api/search, /api/item/<id>, /api/item/<id>/streams
"""

from flask import request, jsonify
import requests


def register(deps):
    bp = deps['bp']
    emby_client = deps['emby_client']
    config = deps['config']
    logger = deps['logger']

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
        logger.info(f"Fetching streams for item ID: {item_id}")

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
