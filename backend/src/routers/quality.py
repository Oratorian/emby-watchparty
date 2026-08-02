"""Quality options router.

Public, anonymous listing of the resolution / bitrate options the per-user
quality dropdown should expose. The frontend reads this on mount instead of
duplicating the table; it also tells the frontend which id is the safe
default to fall back to (`Auto` normally, the 1080p / 10 Mbps preset when
`FORCE_TRANSCODE` is on, or the first available entry when the admin has
disabled the tier the default would belong to).
"""

from fastapi import APIRouter, Depends

from backend.src.dependencies import get_config, get_logger
from backend.src.quality import (
    AUTO_QUALITY_ID,
    DEFAULT_QUALITY_ID,
    build_quality_options,
)
from backend.src.schemas import QualityOption, QualityOptionsResponse

router = APIRouter(prefix="/api", tags=["quality"])


@router.get("/quality-options", response_model=QualityOptionsResponse)
def quality_options(
    config=Depends(get_config),
    logger=Depends(get_logger),
):
    """List the quality dropdown entries for the current admin config.

    Logging note: kept at DEBUG because this is fetched once per video
    mount per client; the request rate is low but uninteresting at INFO.
    """
    force_transcode = bool(config.FORCE_TRANSCODE)
    options = build_quality_options(
        enabled_options=dict(config.ENABLED_QUALITY_OPTIONS or {}),
        force_transcode=force_transcode,
    )

    # Default is `Auto` when stream-copy is still on the table, otherwise
    # the 1080p / 10 Mbps preset (DEFAULT_QUALITY_ID). If the admin has
    # disabled the tier our default belongs to, fall back to whatever the
    # first available entry is so the dropdown never opens with an
    # invalid selection.
    default_id = AUTO_QUALITY_ID if not force_transcode else DEFAULT_QUALITY_ID
    valid_ids = {o["id"] for o in options}
    if default_id not in valid_ids:
        default_id = options[0]["id"] if options else AUTO_QUALITY_ID

    logger.debug(
        f"Quality options served: {len(options)} entries "
        f"(force_transcode={force_transcode}, default={default_id})"
    )
    return QualityOptionsResponse(
        options=[QualityOption(**o) for o in options],
        default_id=default_id,
    )
