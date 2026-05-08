"""
Stream Builder
Quality presets and HLS stream URL parameter construction
"""

import logging
from typing import Optional

from backend.src.emby_client import EmbyClient


QUALITY_PRESETS = {
    "1080p-high": {"max_width": 1920, "max_height": 1080, "bitrate": 10_000_000, "label": "1080p (10 Mbps)"},
    "1080p":      {"max_width": 1920, "max_height": 1080, "bitrate": 8_000_000,  "label": "1080p (8 Mbps)"},
    "720p":       {"max_width": 1280, "max_height": 720,  "bitrate": 4_000_000,  "label": "720p (4 Mbps)"},
    "480p":       {"max_width": 854,  "max_height": 480,  "bitrate": 1_500_000,  "label": "480p (1.5 Mbps)"},
    "360p":       {"max_width": 640,  "max_height": 360,  "bitrate": 500_000,    "label": "360p (0.5 Mbps)"},
}
DEFAULT_QUALITY = "1080p-high"


class StreamBuilder:
    """Builds HLS stream URL parameters for Emby"""

    def __init__(self, emby_client: EmbyClient, logger: logging.Logger):
        self._emby = emby_client
        self._logger = logger

    def build_params(
        self,
        media_source: dict,
        media_source_id: str,
        play_session_id: str,
        audio_index: Optional[int],
        subtitle_index: Optional[int],
        quality: str,
        start_time_ticks: Optional[int] = None,
    ) -> list:
        """
        Build HLS URL parameters for Emby.

        Returns:
            list of 'key=value' parameter strings
        """
        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])
        max_width = preset["max_width"]
        max_height = preset["max_height"]
        max_bitrate = preset["bitrate"]

        source_video_codec = None
        source_video_bitrate = None
        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Video":
                source_video_codec = (stream.get("Codec") or "").lower()
                peak_bitrate = stream.get("MaxBitRate") or stream.get("PeakBitrate")
                avg_bitrate = stream.get("BitRate")
                source_video_bitrate = peak_bitrate or avg_bitrate
                self._logger.info(
                    f"Source video codec: {source_video_codec}, avg_bitrate: {avg_bitrate}, peak_bitrate: {peak_bitrate}"
                )
                break

        transcode_reasons = []
        if source_video_codec and source_video_codec != "h264":
            transcode_reasons.append("VideoCodecNotSupported")
        if not transcode_reasons:
            transcode_reasons.append("ContainerBitrateExceedsLimit")

        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={self._emby.device_id}",
            f"api_key={self._emby.api_key}",
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
            # "EnableAutoStreamCopy=false",  # TEMP: testing whether seek
            # bug from #25 is actually a drift-correction artifact, not
            # caused by stream-copy itself. Re-enable if seeking breaks.
            "MinSegments=1",
            "h264-profile=high,main,baseline,constrainedbaseline",
            "h264-level=62",
            f"TranscodeReasons={','.join(transcode_reasons)}",
        ]

        source_width = None
        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Video":
                source_width = stream.get("Width")
                break

        needs_downscale = source_width and source_width > max_width

        params.append("VideoCodec=h264")
        source_br = source_video_bitrate or max_bitrate
        target_bitrate = min(max_bitrate, source_br)
        params.append(f"VideoBitrate={target_bitrate}")

        if source_video_codec != "h264":
            self._logger.info(
                f"Source is {source_video_codec}, transcoding to h264 at {preset['label']}"
            )
        elif needs_downscale:
            self._logger.info(
                f"Downscaling from {source_width}px to {max_width}px at {preset['label']}"
            )
        else:
            self._logger.info(
                f"Source is h264 at {source_br // 1_000_000}Mbps, "
                f"re-encoding at {target_bitrate // 1_000_000}Mbps for reliable HLS seeking "
                f"(auto stream copy disabled)"
            )

        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
            self._logger.debug(f"Using audio stream index: {audio_index}")
        else:
            self._logger.debug("No audio stream index specified, Emby will use default")

        # Image subtitles (PGS, VobSub) must be burned in because HLS.js cannot
        # render bitmap subtitle formats. Text subtitles are NOT delivered via
        # the HLS manifest -- the frontend preloads them as side-channel
        # <track> elements via /api/subtitles/<item>/<msid>/<idx>. Two parallel
        # subtitle delivery systems (manifest + side-channel) fight over
        # textTrack.mode state, so the manifest path is intentionally off.
        if subtitle_index is not None and subtitle_index != -1:
            is_image_sub = False
            for stream in media_source.get("MediaStreams", []):
                if (
                    stream.get("Type") == "Subtitle"
                    and stream.get("Index") == subtitle_index
                ):
                    codec = stream.get("Codec", "").lower()
                    is_image_sub = codec in [
                        "pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub",
                    ]
                    break

            if is_image_sub:
                params.append(f"SubtitleStreamIndex={subtitle_index}")
                params.append("SubtitleMethod=Encode")
                self._logger.info(f"Burning in image subtitle track {subtitle_index}")
            else:
                self._logger.debug(
                    f"Text subtitle {subtitle_index} delivered via side-channel proxy"
                )
        else:
            self._logger.debug("No subtitle selected for backend transcode")

        if start_time_ticks is not None and start_time_ticks > 0:
            params.append(f"StartTimeTicks={start_time_ticks}")
            self._logger.debug(f"Starting transcode at {start_time_ticks / 10_000_000:.1f}s")

        return params

    def build_stream_url(
        self,
        item_id: str,
        app_prefix: str,
        media_source: dict,
        media_source_id: str,
        play_session_id: str,
        audio_index: Optional[int],
        subtitle_index: Optional[int],
        quality: str,
        start_time_ticks: Optional[int] = None,
    ) -> str:
        """Build the full relative HLS stream URL"""
        params = self.build_params(
            media_source, media_source_id, play_session_id,
            audio_index, subtitle_index, quality, start_time_ticks,
        )
        param_string = "&".join(params)
        prefix = app_prefix or ""
        return f"{prefix}/hls/{item_id}/master.m3u8?{param_string}"


def build_stream_params(emby_client, media_source, media_source_id, play_session_id,
                        audio_index, subtitle_index, quality, logger):
    """Standalone shim for backward compatibility with old handler code."""
    builder = StreamBuilder(emby_client, logger)
    return builder.build_params(
        media_source, media_source_id, play_session_id,
        audio_index, subtitle_index, quality,
    )
