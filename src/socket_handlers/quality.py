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

    # Detect source video codec and bitrate (use peak if available, else average)
    source_video_codec = None
    source_video_bitrate = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_video_codec = (stream.get("Codec") or "").lower()
            peak_bitrate = stream.get("MaxBitRate") or stream.get("PeakBitrate")
            avg_bitrate = stream.get("BitRate")
            source_video_bitrate = peak_bitrate or avg_bitrate
            logger.info(f"Source video codec: {source_video_codec}, avg_bitrate: {avg_bitrate}, peak_bitrate: {peak_bitrate}")
            break

    params = [
        f"MediaSourceId={media_source_id}",
        f"PlaySessionId={play_session_id}",
        f"DeviceId={emby_client.device_id}",
        f"api_key={emby_client.api_key}",
        "SegmentContainer=ts",
        "TranscodingMaxAudioChannels=2",
        "AudioCodec=aac,mp3",
        "AudioBitrate=384000",
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

    # Always force a video transcode, never let Emby stream-copy.
    #
    # The stream-copy ("direct play") HLS path remuxes the source's h264
    # bitstream into ts segments at the SOURCE's keyframe boundaries.
    # Emby still lists segments in the playlist with uniform #EXTINF
    # durations even though the real data is cut on irregular VBR
    # keyframes. When HLS.js seeks to a position that doesn't align
    # with a real keyframe, it either hits a 404 (segment not generated
    # yet) or plays the wrong scene -- this is the root cause of
    # issue #25 and the general "some files can't seek" class of bugs.
    #
    # Forcing VideoCodec=h264 makes Emby re-encode with ffmpeg using
    # a controlled keyframe interval, producing actually-uniform
    # segments that seek reliably. On servers with hardware encoders
    # (QSV/NVENC/VAAPI) this is near-zero CPU cost; on CPU-only
    # servers this costs real cycles but is the only way to make
    # seeking reliable with Emby's HLS output.
    params.append("VideoCodec=h264")
    # Cap bitrate at the quality preset's target. For h264 sources
    # below the cap this still forces re-encoding (which is what we
    # want for reliable seeks), just at a bitrate equal to or lower
    # than the source.
    target_bitrate = min(max_bitrate, source_video_bitrate or max_bitrate)
    params.append(f"VideoBitrate={target_bitrate}")

    if source_video_codec != "h264":
        logger.info(f"Source is {source_video_codec}, transcoding to h264 at {preset['label']}")
    elif needs_downscale:
        logger.info(f"Downscaling from {source_width}px to {max_width}px at {preset['label']}")
    else:
        # Common case: h264 source under cap. Force re-encode to
        # guarantee uniform HLS segments (stream-copy path has broken
        # seeking on some VBR files -- see issue #25).
        logger.info(
            f"Source is h264 at {(source_video_bitrate or 0) // 1_000_000}Mbps, "
            f"re-encoding at {target_bitrate // 1_000_000}Mbps for reliable HLS seeking"
        )

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
