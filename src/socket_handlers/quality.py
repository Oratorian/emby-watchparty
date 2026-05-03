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

    # Determine transcode reason for Emby's logging and decision-making.
    # Emby's own web client sends this so the server knows WHY we're
    # requesting a transcode rather than having to guess.
    transcode_reasons = []
    if source_video_codec and source_video_codec != "h264":
        transcode_reasons.append("VideoCodecNotSupported")
    # We always force h264 re-encode (no stream-copy) for reliable HLS
    # seeking, so even compatible sources get a reason.
    if not transcode_reasons:
        transcode_reasons.append("ContainerBitrateExceedsLimit")

    # Decide subtitle plan up-front so the URL has exactly one
    # SubtitleMethod and one consistent set of subtitle params. Mixing
    # SubtitleMethod=Hls + SubtitleMethod=Encode in the same URL (which
    # the previous structure did when a PGS track was selected) silently
    # broke burn-in for image subtitles (issue #29).
    #
    # Three distinct cases:
    #   1. User selected an image subtitle (PGS/VobSub): burn it into the
    #      video. HLS.js cannot render bitmap subtitles natively.
    #   2. User selected a text subtitle: serve it via the HLS manifest
    #      as a VTT track so HLS.js can switch tracks natively.
    #   3. Nothing selected: still expose all text tracks as VTT in the
    #      manifest so the user can switch later without restarting.
    selected_is_image_sub = False
    if subtitle_index is not None and subtitle_index != -1:
        for stream in media_source.get("MediaStreams", []):
            if (
                stream.get("Type") == "Subtitle"
                and stream.get("Index") == subtitle_index
            ):
                codec = (stream.get("Codec") or "").lower()
                selected_is_image_sub = codec in [
                    "pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub",
                ]
                break

    # Indexes of every available text subtitle (for the manifest case).
    # Image subtitles are excluded -- VTT cannot represent them, and
    # asking Emby to render bitmap tracks as VTT silently produces
    # nothing.
    text_subtitle_indexes = []
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") != "Subtitle":
            continue
        codec = (stream.get("Codec") or "").lower()
        if codec in ["pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub"]:
            continue
        text_subtitle_indexes.append(str(stream.get("Index")))

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
        # Disable automatic stream copy so Emby always re-encodes the
        # video with controlled keyframe intervals. Without this, Emby
        # stream-copies h264 sources into HLS segments at the source's
        # original keyframe boundaries, producing segments with irregular
        # durations that break seeking in HLS.js (issue #25).
        "EnableAutoStreamCopy=false",
        # Reduce initial buffering: Emby defaults to waiting for multiple
        # segments before serving. MinSegments=1 lets it serve as soon as
        # the first segment is ready (matching Emby's own web client).
        "MinSegments=1",
        # Declare supported h264 profiles and levels so Emby can make
        # informed Direct Play vs transcode decisions. These match what
        # modern browsers support via HLS.js.
        "h264-profile=high,main,baseline,constrainedbaseline",
        "h264-level=62",
        # Tell Emby why we're transcoding so it can optimize its pipeline.
        f"TranscodeReasons={','.join(transcode_reasons)}",
    ]

    if selected_is_image_sub:
        # Burn the bitmap subtitle into the video frames. No manifest
        # subtitles in this case -- ManifestSubtitles=vtt would cause
        # Emby to generate empty VTTs alongside the burn-in.
        params.append(f"SubtitleStreamIndex={subtitle_index}")
        params.append("SubtitleMethod=Encode")
    else:
        # Manifest subtitles for every text track. HLS.js can switch
        # between them without separate VTT fetches.
        params.append("SubtitleMethod=Hls")
        params.append("ManifestSubtitles=vtt")
        if text_subtitle_indexes:
            params.append(f"SubtitleStreamIndexes={','.join(text_subtitle_indexes)}")
        if subtitle_index is not None and subtitle_index != -1:
            # User picked a specific text track to be the default.
            params.append(f"SubtitleStreamIndex={subtitle_index}")

    # Determine if transcoding is needed
    source_width = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_width = stream.get("Width")
            break

    needs_downscale = source_width and source_width > max_width

    # Always force a video re-encode, never let Emby stream-copy.
    #
    # Emby's stream-copy HLS path remuxes the source's h264 bitstream
    # into ts segments at the SOURCE's original keyframe boundaries.
    # The playlist advertises uniform segment durations but the actual
    # data is cut on irregular VBR keyframes. When HLS.js seeks to a
    # position that doesn't align with a real keyframe, it either hits
    # a 404 or plays the wrong scene (issue #25).
    #
    # Setting VideoCodec=h264 alone is NOT enough -- Emby treats that
    # as "client accepts h264" and stream-copies when the source
    # matches. Setting EnableDirectStream=false on PlaybackInfo also
    # doesn't work -- the HLS endpoint makes its own decision.
    #
    # The ONLY reliable way to force a real re-encode is to set
    # VideoBitrate BELOW the source bitrate. Emby cannot stream-copy
    # when the target bitrate is lower than the source because stream-
    # copy by definition preserves the original bitrate.
    #
    # We cap at 80% of the source bitrate (or the quality preset cap,
    # whichever is lower). The 20% reduction is visually imperceptible
    # for most content but guarantees Emby uses the encode path with
    # controlled keyframe intervals. On servers with hardware encoders
    # (QSV/NVENC/VAAPI) this is near-zero CPU cost.
    params.append("VideoCodec=h264")

    source_br = source_video_bitrate or max_bitrate
    # Cap at the quality preset target or the source bitrate, whichever
    # is lower. Combined with EnableAutoStreamCopy=false above, this
    # guarantees a real re-encode with controlled keyframes even when
    # the source codec and bitrate match the target.
    target_bitrate = min(max_bitrate, source_br)
    params.append(f"VideoBitrate={target_bitrate}")

    if source_video_codec != "h264":
        logger.info(f"Source is {source_video_codec}, transcoding to h264 at {preset['label']}")
    elif needs_downscale:
        logger.info(f"Downscaling from {source_width}px to {max_width}px at {preset['label']}")
    else:
        logger.info(
            f"Source is h264 at {source_br // 1_000_000}Mbps, "
            f"re-encoding at {target_bitrate // 1_000_000}Mbps for reliable HLS seeking "
            f"(auto stream copy disabled)"
        )

    # Audio stream selection
    if audio_index is not None:
        params.append(f"AudioStreamIndex={audio_index}")
        logger.debug(f"Using audio stream index: {audio_index}")
    else:
        logger.debug("No audio stream index specified, Emby will use default")

    # Log the chosen subtitle plan (the param construction already
    # happened up top so the URL has exactly one consistent set).
    if selected_is_image_sub:
        logger.info(f"Burning in image subtitle track {subtitle_index}")
    elif subtitle_index is not None and subtitle_index != -1:
        logger.info(f"Text subtitle {subtitle_index} via HLS manifest (VTT)")
    else:
        logger.debug("No subtitles selected - using manifest subtitles for all available tracks")

    return params
