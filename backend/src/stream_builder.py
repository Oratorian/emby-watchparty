"""
Stream Builder
Turn a quality-id into the right Emby HLS URL parameters.

Quality definitions live in `backend.src.quality`. This module only knows
how to consume a quality id (`auto`, `360p`, `1080p-15000`, etc.) and
emit the matching `MaxWidth` / `MaxHeight` / `VideoBitrate` triple, plus
the rest of the static HLS parameter pack.
"""

import logging

from backend.src.config import Config
from backend.src.emby_client import EmbyClient
from backend.src.quality import resolve_quality


class StreamBuilder:
    """Builds HLS stream URL parameters for Emby."""

    def __init__(
        self, emby_client: EmbyClient, logger: logging.Logger, config: Config | None = None
    ):
        self._emby = emby_client
        self._logger = logger
        self._config = config

    def build_params(
        self,
        media_source: dict,
        media_source_id: str,
        play_session_id: str,
        audio_index: int | None,
        subtitle_index: int | None,
        quality: str,
        start_time_ticks: int | None = None,
        client_codecs: set[str] | None = None,
    ) -> list:
        """Build HLS URL parameters for Emby.

        `quality` is a quality-id string (see backend/src/quality.py):
        the sentinel `auto` (no caps), a resolution-only id like `360p`,
        or a `<resolution>-<kbps>` id like `1080p-15000`. Unknown or
        legacy ids fall back to the closest current equivalent via
        `resolve_quality`.

        `client_codecs` is the set of video codecs this specific viewer
        reported it can decode, e.g. `{"h264", "hevc"}`. Streams are built
        per viewer, so this is per viewer too: whether the source stays in
        its own codec is a property of the browser asking, not of the
        party. `None` means the client told us nothing, which is treated
        as h264-only because that is the one codec every target browser
        decodes.

        Returns a list of `key=value` parameter strings (joined later by
        `build_stream_url`).
        """
        max_width, max_height, bitrate_kbps = resolve_quality(quality)

        source_video_codec: str | None = None
        source_video_bitrate: int | None = None
        source_width: int | None = None
        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Video":
                source_video_codec = (stream.get("Codec") or "").lower()
                peak_bitrate = stream.get("MaxBitRate") or stream.get("PeakBitrate")
                avg_bitrate = stream.get("BitRate")
                source_video_bitrate = peak_bitrate or avg_bitrate
                source_width = stream.get("Width")
                self._logger.info(
                    f"Source video codec: {source_video_codec}, "
                    f"avg_bitrate: {avg_bitrate}, peak_bitrate: {peak_bitrate}"
                )
                break

        # Which codec this viewer actually gets. Historically this was
        # always h264: a lowest-common-denominator choice made server-side
        # with no idea what the browser could decode, so an HEVC source was
        # re-encoded even for a client that would have played it directly
        # (#61). The client now reports what it can decode, and because
        # streams are already built per viewer, the answer can differ
        # between two people in the same party.
        #
        # Falling back to h264 whenever the client said nothing keeps the
        # old behaviour for any client that has not been updated, and for
        # the ones that genuinely cannot decode anything else.
        supported = {codec.lower() for codec in (client_codecs or ())} or {"h264"}
        keep_source_codec = bool(source_video_codec) and source_video_codec in supported
        target_video_codec = source_video_codec if keep_source_codec else "h264"

        # TranscodeReasons is informational -- Emby uses it for logging
        # and telemetry, not for the transcode-or-copy decision itself.
        # We only set it when we actually want a transcode (a source the
        # viewer cannot decode, or an explicit bitrate cap). Leaving it
        # empty is what lets Emby stream-copy.
        transcode_reasons = []
        if not keep_source_codec and source_video_codec and source_video_codec != "h264":
            transcode_reasons.append("VideoCodecNotSupported")
        elif bitrate_kbps is not None:
            transcode_reasons.append("ContainerBitrateExceedsLimit")

        # NO api_key in the stream URL. Historically this embedded the
        # admin EMBY_API_KEY so any party viewer could read the value
        # from `<video>.src` in DevTools and gain full admin access to
        # the Emby server. The /hls/... proxy authenticates upstream via
        # the party's host_access_token (routers/hls.py:_resolve_host_creds),
        # so the raw URL never needs to carry credentials to Emby. Keep
        # this out of every future param dict.
        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={self._emby.device_id}",
            "SegmentContainer=ts",
            "TranscodingMaxAudioChannels=2",
            "AudioCodec=aac,mp3",
            "AudioBitrate=384000",
            "BreakOnNonKeyFrames=True",
            "MaxAudioChannels=2",
            "MinSegments=1",
            "h264-profile=high,main,baseline,constrainedbaseline",
            "h264-level=62",
            f"VideoCodec={target_video_codec}",
        ]

        if max_width is not None:
            params.append(f"MaxWidth={max_width}")
        if max_height is not None:
            params.append(f"MaxHeight={max_height}")
        if transcode_reasons:
            params.append(f"TranscodeReasons={','.join(transcode_reasons)}")

        # Runtime-toggleable: when FORCE_TRANSCODE is on we tell Emby to
        # skip stream-copy and re-encode every h264 source. That gives
        # uniform 6s HLS segments at the cost of CPU/GPU on the Emby
        # host. Default off -- only useful when stream-copied sources
        # misbehave on large seeks (Skip Intro / timeline drag) or
        # HLS.js can't seek into them cleanly.
        if self._config and self._config.FORCE_TRANSCODE:
            params.append("EnableAutoStreamCopy=false")

        # Bitrate cap: only when an explicit kbps was selected. Clamp to
        # the source bitrate if it is lower (no benefit to a higher
        # target than what the source has).
        target_bitrate: int | None = None
        if bitrate_kbps is not None:
            target_bitrate = bitrate_kbps * 1000
            if source_video_bitrate and source_video_bitrate < target_bitrate:
                target_bitrate = source_video_bitrate
            params.append(f"VideoBitrate={target_bitrate}")

        # Human-readable summary of what we asked Emby to do. These read
        # the same values that built the params, so the log cannot claim a
        # transcode the URL did not request; the codec line was previously
        # written independently and went stale the moment the parameter
        # changed (#61).
        if keep_source_codec and source_video_codec != "h264":
            self._logger.info(
                f"Source is {source_video_codec} and the client decodes it; "
                f"keeping {source_video_codec}"
                + (f" at {target_bitrate // 1000} kbps" if target_bitrate else " (no bitrate cap)")
            )
        elif source_video_codec and source_video_codec != "h264":
            if target_bitrate is not None:
                self._logger.info(
                    f"Source is {source_video_codec}, client cannot decode it, "
                    f"transcoding to h264 at "
                    f"{max_width}x{max_height} / {target_bitrate // 1000} kbps"
                )
            elif max_width is not None:
                self._logger.info(
                    f"Source is {source_video_codec}, client cannot decode it, "
                    f"transcoding to h264 at {max_width}x{max_height} (no bitrate cap)"
                )
            else:
                self._logger.info(
                    f"Source is {source_video_codec}, client cannot decode it, "
                    f"transcoding to h264 (Auto, no caps)"
                )
        elif target_bitrate is not None:
            if max_width is not None and source_width and source_width > max_width:
                self._logger.info(
                    f"Downscaling from {source_width}px to {max_width}px at "
                    f"{target_bitrate // 1000} kbps cap"
                )
            else:
                source_mbps = (source_video_bitrate or target_bitrate) // 1_000_000
                target_mbps = target_bitrate // 1_000_000
                self._logger.info(
                    f"Source is h264 at {source_mbps} Mbps, re-encoding at "
                    f"{target_mbps} Mbps for reliable HLS seeking"
                )
        elif max_width is not None:
            self._logger.info(
                f"Source is h264, capping resolution at {max_width}x{max_height} (no bitrate cap)"
            )
        else:
            self._logger.info("Source is h264, Auto quality -> Emby decides (stream-copy possible)")

        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
            self._logger.debug(f"Using audio stream index: {audio_index}")
        else:
            self._logger.debug("No audio stream index specified, Emby will use default")

        # Image subtitles (PGS, VobSub) must be burned in because HLS.js
        # cannot render bitmap subtitle formats. Text subtitles are NOT
        # delivered via the HLS manifest -- the frontend preloads them
        # as side-channel <track> elements via
        # /api/subtitles/<item>/<msid>/<idx>. Two parallel subtitle
        # delivery systems (manifest + side-channel) fight over
        # textTrack.mode state, so the manifest path is intentionally off.
        if subtitle_index is not None and subtitle_index != -1:
            is_image_sub = False
            for stream in media_source.get("MediaStreams", []):
                if stream.get("Type") == "Subtitle" and stream.get("Index") == subtitle_index:
                    codec = stream.get("Codec", "").lower()
                    is_image_sub = codec in [
                        "pgssub",
                        "pgs",
                        "dvd_subtitle",
                        "dvdsub",
                        "vobsub",
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
        audio_index: int | None,
        subtitle_index: int | None,
        quality: str,
        start_time_ticks: int | None = None,
        client_codecs: set[str] | None = None,
    ) -> str:
        """Build the full relative HLS stream URL"""
        params = self.build_params(
            media_source,
            media_source_id,
            play_session_id,
            audio_index,
            subtitle_index,
            quality,
            start_time_ticks,
            client_codecs=client_codecs,
        )
        param_string = "&".join(params)
        prefix = app_prefix or ""
        return f"{prefix}/hls/{item_id}/master.m3u8?{param_string}"
