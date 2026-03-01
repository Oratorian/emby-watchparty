"""
Quality Presets and Stream Parameter Builder
Shared constants and helper used by playback handlers.
"""


QUALITY_PRESETS = {
    "1080p-high": {"max_width": 1920, "max_height": 1080, "bitrate": 10_000_000, "label": "1080p (10 Mbps)"},
    "1080p":      {"max_width": 1920, "max_height": 1080, "bitrate": 8_000_000,  "label": "1080p (8 Mbps)"},
    "720p":       {"max_width": 1280, "max_height": 720,  "bitrate": 4_000_000,  "label": "720p (4 Mbps)"},
    "480p":       {"max_width": 854,  "max_height": 480,  "bitrate": 1_500_000,  "label": "480p (1.5 Mbps)"},
    "360p":       {"max_width": 640,  "max_height": 360,  "bitrate": 500_000,    "label": "360p (0.5 Mbps)"},
}
DEFAULT_QUALITY = "1080p-high"


def build_stream_params(emby_client, media_source, media_source_id, play_session_id,
                        audio_index, subtitle_index, quality, logger):
    """
    Build HLS stream URL parameters for Emby.

    Args:
        emby_client: EmbyClient instance (for device_id, api_key)
        media_source: MediaSource dict from Emby PlaybackInfo
        media_source_id: MediaSource ID string
        play_session_id: PlaySession ID string
        audio_index: Audio stream index (int or None)
        subtitle_index: Subtitle stream index (int or None)
        quality: Quality preset key (e.g. "1080p", "720p")
        logger: Logger instance

    Returns:
        list of URL parameter strings
    """
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])
    max_width = preset["max_width"]
    max_height = preset["max_height"]
    max_bitrate = preset["bitrate"]

    # Detect source video codec and bitrate
    source_video_codec = None
    source_video_bitrate = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_video_codec = (stream.get("Codec") or "").lower()
            source_video_bitrate = stream.get("BitRate")
            logger.info(f"Source video codec: {source_video_codec}, bitrate: {source_video_bitrate}")
            break

    params = [
        f"MediaSourceId={media_source_id}",
        f"PlaySessionId={play_session_id}",
        f"DeviceId={emby_client.device_id}",
        f"api_key={emby_client.api_key}",
        "SegmentContainer=ts",
        "TranscodingMaxAudioChannels=2",
        "AudioCodec=aac,mp3",
        "BreakOnNonKeyFrames=True",
        "MaxAudioChannels=2",
        f"MaxWidth={max_width}",
        f"MaxHeight={max_height}",
    ]

    # Determine if transcoding is needed
    source_width = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_width = stream.get("Width")
            break

    needs_downscale = source_width and source_width > max_width

    if source_video_codec != "h264" or needs_downscale:
        params.append("VideoCodec=h264")
        params.append(f"VideoBitrate={max_bitrate}")
        if source_video_codec != "h264":
            logger.info(f"Source is {source_video_codec}, transcoding to h264 at {preset['label']}")
        else:
            logger.info(f"Downscaling from {source_width}px to {max_width}px at {preset['label']}")
    elif source_video_bitrate and source_video_bitrate > max_bitrate:
        params.append("VideoCodec=h264")
        params.append(f"VideoBitrate={max_bitrate}")
        logger.info(f"Source is h264 but bitrate {source_video_bitrate // 1_000_000}Mbps exceeds cap, transcoding at {preset['label']}")
    else:
        logger.info(f"Source is h264 at {(source_video_bitrate or 0) // 1_000_000}Mbps, quality preset {preset['label']}")

    # Audio stream selection
    if audio_index is not None:
        params.append(f"AudioStreamIndex={audio_index}")
        logger.debug(f"Using audio stream index: {audio_index}")
    else:
        logger.debug("No audio stream index specified, Emby will use default")

    # Subtitle handling
    if subtitle_index is not None and subtitle_index != -1:
        is_pgs = False
        for stream in media_source["MediaStreams"]:
            if (
                stream.get("Type") == "Subtitle"
                and stream.get("Index") == subtitle_index
            ):
                codec = stream.get("Codec", "").lower()
                is_pgs = codec in [
                    "pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub",
                ]
                break

        if is_pgs:
            params.append(f"SubtitleStreamIndex={subtitle_index}")
            params.append("SubtitleMethod=Encode")
            logger.info(f"Burning in PGS subtitle track {subtitle_index}")
        else:
            logger.info(f"Text subtitle {subtitle_index} will be loaded separately as VTT")
    else:
        logger.debug("No subtitles selected - omitting subtitle parameters")

    return params
