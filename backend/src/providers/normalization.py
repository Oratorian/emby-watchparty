"""Normalize Emby-family payloads into provider-neutral domain objects."""

from __future__ import annotations

import re
from dataclasses import asdict, fields

from backend.src.providers.models import (
    AudioStream,
    CatalogQuery,
    MediaItem,
    MediaItemDetails,
    MediaPage,
    MediaVersion,
    StreamCatalog,
    SubtitleStream,
    UserMediaState,
)

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


def normalize_details(raw: dict) -> MediaItemDetails:
    item = normalize_item(raw)
    people = tuple(
        {
            "id": str(person.get("Id") or ""),
            "name": str(person.get("Name") or ""),
            "kind": _snake(person.get("Type")),
        }
        for person in raw.get("People", [])
        if isinstance(person, dict) and person.get("Name")
    )
    studios = tuple(
        str(studio.get("Name") if isinstance(studio, dict) else studio)
        for studio in raw.get("Studios", [])
        if (studio.get("Name") if isinstance(studio, dict) else studio)
    )
    item_values = {field.name: getattr(item, field.name) for field in fields(MediaItem)}
    return MediaItemDetails(
        **item_values,
        genres=tuple(str(value) for value in raw.get("Genres", []) if value),
        tags=tuple(str(value) for value in raw.get("Tags", []) if value),
        people=people,
        studios=studios,
        official_rating=raw.get("OfficialRating"),
        community_rating=raw.get("CommunityRating"),
        critic_rating=raw.get("CriticRating"),
    )


def normalize_stream_catalog(scoped: dict, full: dict) -> StreamCatalog:
    versions = tuple(
        MediaVersion(
            id=str(source["Id"]),
            name=str(source.get("Name") or source.get("Container") or source["Id"]),
            container=source.get("Container"),
            runtime_seconds=(
                float(source["RunTimeTicks"]) / 10_000_000
                if source.get("RunTimeTicks") is not None
                else None
            ),
        )
        for source in full.get("MediaSources", []) or []
        if source.get("Id")
    )
    source = next(iter(scoped.get("MediaSources", []) or []), None)
    streams = source.get("MediaStreams", []) if source else scoped.get("MediaStreams", [])
    audio: list[AudioStream] = []
    subtitles: list[SubtitleStream] = []
    image_codecs = {"pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub"}
    for stream in streams or []:
        language = str(stream.get("Language") or "und")
        display = str(stream.get("DisplayLanguage") or stream.get("DisplayTitle") or language)
        if language == "und":
            display = "Unknown"
        if stream.get("Type") == "Audio":
            audio.append(
                AudioStream(
                    index=int(stream.get("Index") or 0),
                    language=language,
                    display_language=display,
                    codec=str(stream.get("Codec") or ""),
                    channels=int(stream.get("Channels") or 0),
                    is_default=bool(stream.get("IsDefault")),
                    title=str(stream.get("Title") or ""),
                )
            )
        elif stream.get("Type") == "Subtitle":
            codec = str(stream.get("Codec") or "")
            subtitles.append(
                SubtitleStream(
                    index=int(stream.get("Index") or 0),
                    language=language,
                    display_language=display,
                    codec=codec,
                    is_default=bool(stream.get("IsDefault")),
                    is_forced=bool(stream.get("IsForced")),
                    is_external=bool(stream.get("IsExternal")),
                    is_text=bool(stream.get("IsTextSubtitleStream")),
                    is_image=codec.lower() in image_codecs,
                    title=str(stream.get("Title") or ""),
                )
            )
    return StreamCatalog(
        audio=tuple(audio),
        subtitles=tuple(subtitles),
        media_source_id=str(source.get("Id")) if source and source.get("Id") else None,
        versions=versions,
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
        "filters": asdict(query.filters),
        "search_term": query.search_term,
        "anchor_prefix": query.anchor_prefix,
    }
