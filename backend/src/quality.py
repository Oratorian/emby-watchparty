"""Quality tiers for the per-user stream picker.

Mirrors Emby's own resolution/bitrate buckets so the curation work is not
duplicated -- their per-resolution caps are already tuned to be visually
sensible (4 Mbps is the realistic top for 720p, 1 Mbps for 480p, etc.).

The user-visible dropdown is a single flat list rendered from
`build_quality_options()`. The admin chooses which resolutions appear AND
which bitrates within each resolution via
`RuntimeConfig.ENABLED_QUALITY_OPTIONS` -- a dict mapping resolution ->
list of enabled kbps. Presence of a key enables the resolution; an empty
value list is only meaningful for the resolution-only tiers (360p / 240p
/ 144p, which have no bitrate buckets). For 1080p / 720p / 480p an empty
list means "resolution enabled, no bitrates exposed" and the resolution
collapses to nothing in the dropdown.

`Auto` is always available regardless of the enabled set. It sends no
resolution or bitrate cap to Emby, which is the only way stream-copy stays
on the table (any explicit `MaxStreamingBitrate` makes Emby transcode, same
as their web client).
"""

# Resolution -> {width, height, bitrates_kbps}. Mirrors Emby's quality menu.
# Bitrates are in kbps so the 720 / 420 kbps 480p options can be expressed
# precisely without losing the sub-Mbps detail to integer division.
QUALITY_TIERS: dict[str, dict] = {
    "1080p": {
        "width": 1920,
        "height": 1080,
        "bitrates_kbps": [
            60_000,
            50_000,
            40_000,
            30_000,
            25_000,
            20_000,
            15_000,
            12_000,
            10_000,
            8_000,
            6_000,
            5_000,
            4_000,
        ],
    },
    "720p": {"width": 1280, "height": 720, "bitrates_kbps": [4_000, 3_000, 2_000, 1_500, 1_000]},
    "480p": {"width": 854, "height": 480, "bitrates_kbps": [1_000, 720, 420]},
    "360p": {"width": 640, "height": 360, "bitrates_kbps": []},
    "240p": {"width": 426, "height": 240, "bitrates_kbps": []},
    "144p": {"width": 256, "height": 144, "bitrates_kbps": []},
}

# Order the resolution tiers appear in the dropdown (highest first).
RESOLUTION_ORDER = ("1080p", "720p", "480p", "360p", "240p", "144p")


# Default: every resolution enabled, every bitrate exposed. Stored as a
# function so callers always get a fresh copy (lists are mutable).
def _default_enabled_options() -> dict[str, list[int]]:
    return {res: list(QUALITY_TIERS[res]["bitrates_kbps"]) for res in RESOLUTION_ORDER}


DEFAULT_ENABLED_OPTIONS = _default_enabled_options()

# The default quality id stored on a freshly-selected video. Matches the
# behaviour of the previous "1080p-high" preset (1080p, ~10 Mbps cap).
DEFAULT_QUALITY_ID = "1080p-10000"

AUTO_QUALITY_ID = "auto"

# Map from the pre-2.0-rwrk preset names to their nearest equivalent in
# the new id space, so existing in-memory party state keeps working on
# read without a migration step.
_LEGACY_PRESET_MAP = {
    "1080p-high": "1080p-10000",
    "1080p": "1080p-8000",
    "720p": "720p-4000",
    "480p": "480p-1000",
    "360p": "360p",
}


def _format_bitrate(kbps: int) -> str:
    """Render a bitrate in Mbps when >= 1000, otherwise in kbps."""
    if kbps >= 1000 and kbps % 1000 == 0:
        return f"{kbps // 1000} Mbps"
    if kbps >= 1000:
        # 1500 -> "1.5 Mbps"; trim trailing .0
        mbps = kbps / 1000
        return f"{mbps:g} Mbps"
    return f"{kbps} kbps"


def _option_id(resolution: str, kbps: int | None) -> str:
    """Stable id used by the frontend and stored on the party video."""
    if kbps is None:
        return resolution
    return f"{resolution}-{kbps}"


def build_quality_options(
    enabled_options: dict[str, list[int]],
    force_transcode: bool = False,
) -> list[dict]:
    """Emit the flat list of quality options to send to the frontend.

    Begins with the `Auto` entry (only when `FORCE_TRANSCODE` is off --
    Auto means no caps, which conflicts with always-transcode and would
    let the bitrate balloon on h265 sources). Then walks the enabled
    dict: for resolution-only tiers (360p / 240p / 144p, which have no
    bitrate buckets) the resolution itself becomes a single entry. For
    bitrate tiers (1080p / 720p / 480p) only the admin's chosen kbps
    subset is exposed, intersected with the canonical tier list so a
    bad config payload can't smuggle in arbitrary values.
    """
    options: list[dict] = []
    if not force_transcode:
        options.append(
            {
                "id": AUTO_QUALITY_ID,
                "label": "Auto",
                "resolution": None,
                "width": None,
                "height": None,
                "bitrate_kbps": None,
            }
        )
    enabled = enabled_options or {}
    for resolution in RESOLUTION_ORDER:
        if resolution not in enabled:
            continue
        tier = QUALITY_TIERS[resolution]
        tier_bitrates = tier["bitrates_kbps"]
        if not tier_bitrates:
            # Resolution-only tier (360p / 240p / 144p). Always emit a
            # single entry; the admin's value list is ignored here since
            # there are no bitrates to subset.
            options.append(
                {
                    "id": _option_id(resolution, None),
                    "label": resolution,
                    "resolution": resolution,
                    "width": tier["width"],
                    "height": tier["height"],
                    "bitrate_kbps": None,
                }
            )
            continue
        allowed = set(enabled[resolution] or ())
        for kbps in tier_bitrates:
            if kbps not in allowed:
                continue
            options.append(
                {
                    "id": _option_id(resolution, kbps),
                    "label": f"{resolution} - {_format_bitrate(kbps)}",
                    "resolution": resolution,
                    "width": tier["width"],
                    "height": tier["height"],
                    "bitrate_kbps": kbps,
                }
            )
    return options


def resolve_quality(quality_id: str | None) -> tuple[int | None, int | None, int | None]:
    """Map a quality id to (max_width, max_height, bitrate_kbps).

    Returns `(None, None, None)` for `Auto`, unknown ids, or a bare
    legacy preset that no longer exists. Legacy 1.x preset strings
    (`1080p-high`, `1080p`, `720p`, `480p`, `360p`) are translated to the
    nearest current id so stored party state keeps working on read.

    Returning `(width, height, None)` -- a resolution cap with no bitrate
    cap -- is intentional for the 360p / 240p / 144p tiers.
    """
    if not quality_id or quality_id == AUTO_QUALITY_ID:
        return (None, None, None)
    quality_id = _LEGACY_PRESET_MAP.get(quality_id, quality_id)

    if "-" in quality_id:
        resolution, _, kbps_str = quality_id.partition("-")
        try:
            kbps: int | None = int(kbps_str)
        except ValueError:
            return (None, None, None)
    else:
        resolution = quality_id
        kbps = None

    tier = QUALITY_TIERS.get(resolution)
    if not tier:
        return (None, None, None)
    return (tier["width"], tier["height"], kbps)


def normalise_quality_id(
    quality_id: str | None,
    force_transcode: bool = False,
) -> str:
    """Canonicalise a stored or incoming quality id.

    Validates against the hardcoded `QUALITY_TIERS` so a client cannot
    fabricate arbitrary bitrates (the buckets are curated, not free-form).
    Translates legacy presets to their new equivalent, falls back to
    `DEFAULT_QUALITY_ID` when the input is missing or unrecognised. When
    `force_transcode` is on, the `Auto` id (which is incompatible with
    always-transcode) is also coerced to the default, matching the
    dropdown which hides Auto in that mode.
    """
    if not quality_id:
        return DEFAULT_QUALITY_ID
    quality_id = _LEGACY_PRESET_MAP.get(quality_id, quality_id)
    if quality_id == AUTO_QUALITY_ID:
        return DEFAULT_QUALITY_ID if force_transcode else AUTO_QUALITY_ID

    if "-" in quality_id:
        resolution, _, kbps_str = quality_id.partition("-")
        try:
            kbps = int(kbps_str)
        except ValueError:
            return DEFAULT_QUALITY_ID
        tier = QUALITY_TIERS.get(resolution)
        if tier and kbps in tier["bitrates_kbps"]:
            return quality_id
        return DEFAULT_QUALITY_ID

    # Bare resolution (e.g. "360p"). Only valid for tiers that have no
    # bitrate buckets; "1080p" without a bitrate is rejected because the
    # 1080p tier requires an explicit bitrate to disambiguate.
    tier = QUALITY_TIERS.get(quality_id)
    if tier and not tier["bitrates_kbps"]:
        return quality_id
    return DEFAULT_QUALITY_ID
