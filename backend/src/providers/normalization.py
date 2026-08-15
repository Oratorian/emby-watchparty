"""Normalize Emby-family payloads into provider-neutral domain objects."""

from __future__ import annotations

import re

from backend.src.providers.models import CatalogQuery, MediaItem, MediaPage, UserMediaState

_PLAYABLE = frozenset(
    {"audio", "episode", "livetvprogram", "movie", "musicvideo", "trailer", "video"}
)
_BROWSABLE = frozenset(
    {
        "boxset",
        "collectionfolder",
        "folder",
        "genre",
        "musicgenre",
        "person",
        "playlist",
        "season",
        "series",
        "studio",
    }
)


def _snake(value: object | None, fallback: str = "other") -> str:
    if not value:
        return fallback
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", str(value)).replace("-", "_")
    return text.lower()


def normalize_item(raw: dict) -> MediaItem:
    kind = _snake(raw.get("Type"))
    user_data = raw.get("UserData") or {}
    runtime_ticks = raw.get("RunTimeTicks")
    position_ticks = user_data.get("PlaybackPositionTicks") or 0
    image_tags = raw.get("ImageTags") or {}
    media_sources = raw.get("MediaSources") or []
    source_count = raw.get("MediaSourceCount")
    return MediaItem(
        id=str(raw.get("Id") or ""),
        name=str(raw.get("Name") or ""),
        kind=kind,
        collection_kind=_snake(raw.get("CollectionType"), "") or None,
        overview=str(raw.get("Overview") or ""),
        runtime_seconds=float(runtime_ticks) / 10_000_000 if runtime_ticks is not None else None,
        production_year=raw.get("ProductionYear"),
        parent_id=raw.get("ParentId"),
        series_id=raw.get("SeriesId"),
        series_name=raw.get("SeriesName"),
        season_id=raw.get("SeasonId"),
        season_name=raw.get("SeasonName"),
        index_number=raw.get("IndexNumber"),
        parent_index_number=raw.get("ParentIndexNumber"),
        is_folder=bool(raw.get("IsFolder")),
        is_playable=kind.replace("_", "") in _PLAYABLE,
        is_browsable=bool(raw.get("IsFolder")) or kind.replace("_", "") in _BROWSABLE,
        has_primary_image=bool(image_tags.get("Primary")),
        backdrop_count=len(raw.get("BackdropImageTags") or []),
        primary_image_aspect_ratio=raw.get("PrimaryImageAspectRatio"),
        user_state=UserMediaState(
            playback_position_seconds=float(position_ticks) / 10_000_000,
            played_percentage=user_data.get("PlayedPercentage"),
            played=bool(user_data.get("Played")),
            favorite=bool(user_data.get("IsFavorite")),
        ),
        media_source_count=int(source_count if source_count is not None else len(media_sources)),
    )


def normalize_page(raw: dict) -> MediaPage:
    return MediaPage(
        items=tuple(normalize_item(item) for item in raw.get("Items", [])),
        total=raw.get("TotalRecordCount"),
        start=int(raw.get("StartIndex") or 0),
    )


def emby_family_query(query: CatalogQuery) -> dict:
    sort_fields = {
        "name": "SortName",
        "date_created": "DateCreated",
        "premiere_date": "PremiereDate",
        "year": "ProductionYear",
        "community_rating": "CommunityRating",
        "critic_rating": "CriticRating",
        "runtime": "Runtime",
        "random": "Random",
    }
    kind_names = {
        "box_set": "BoxSet",
        "episode": "Episode",
        "movie": "Movie",
        "person": "Person",
        "playlist": "Playlist",
        "season": "Season",
        "series": "Series",
        "video": "Video",
    }
    return {
        "scope": {
            "parent_id": query.scope.parent_id,
            "include_item_types": [
                kind_names.get(kind, "".join(part.title() for part in kind.split("_")))
                for kind in query.scope.include_kinds
            ],
            "media_types": [kind.title() for kind in query.scope.media_kinds],
            "recursive": query.scope.recursive,
        },
        "page": {"start_index": query.page.start, "limit": query.page.limit},
        "sort": {
            "field": sort_fields[query.sort.field],
            "direction": query.sort.direction.title(),
        },
        "filters": {
            "playstate": "any",
            "favorite": None,
            "duplicates": None,
            "genres": [],
            "official_ratings": [],
            "studios": [],
            "tags": [],
            "person_ids": [],
            "years": [],
            "containers": [],
            "video_codecs": [],
            "video_types": [],
            "resolutions": [],
            "is_3d": None,
            "audio_codecs": [],
            "audio_layouts": [],
            "audio_languages": [],
            "subtitles": "any",
            "subtitle_codecs": [],
            "subtitle_languages": [],
            "trailers": "any",
            "extras": "any",
            "theme_songs": "any",
            "theme_videos": "any",
            "locked": "any",
            "overview": "any",
            "missing_provider_ids": [],
        },
        "search_term": query.search_term,
        "anchor_prefix": None,
    }
