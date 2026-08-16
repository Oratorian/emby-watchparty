/**
 * Compile-time proof that the hand-written API types still accept what the
 * backend actually sends.
 *
 * api.generated.ts is rendered from the FastAPI response models and guarded by
 * a CI drift check, but nothing imported it, so the gate could only ever
 * detect that the generated file was stale relative to the backend. It could
 * not detect the drift it exists to catch: the hand-written types in
 * api/client.ts, which are what every component actually reads, diverging from
 * the contract the server serves.
 *
 * Each assertion below fails `vue-tsc` if a backend response gains a field
 * shape the frontend type no longer accepts. Direction matters: the value at
 * runtime is whatever the backend sends, so Generated must be assignable to
 * HandWritten, not the other way round.
 *
 * This file has no runtime output. It exists purely to be typechecked.
 */

import type * as Generated from './api.generated'
import type {
  AuthResponse,
  FilterControl,
  FilterOption,
  FilterOptionsResponse,
  GroupedSearchResponse,
  ItemChildrenResponse,
  ItemSectionResponse,
  LibraryItem,
  LibraryPrefixesResponse,
  PlaylistListResponse,
  SearchGroup,
  SuccessResponse,
} from '@/api/client'

/** Asserts every `From` value is a valid `To` value. */
type Satisfies<To, From extends To> = From

type _FilterOption = Satisfies<FilterOption, Generated.FilterOption>
type _FilterControl = Satisfies<FilterControl, Generated.FilterControl>
type _FilterOptions = Satisfies<FilterOptionsResponse, Generated.FilterOptionsResponse>
type _LibraryPrefixes = Satisfies<LibraryPrefixesResponse, Generated.LibraryPrefixesResponse>

/**
 * LibraryItem is checked on field PRESENCE rather than full assignability.
 *
 * The backend model declares most fields `X | None`, while the frontend
 * declares the structured shapes its components actually rely on
 * (ImageTags.Primary, UserData.PlayedPercentage) where the generated type only
 * knows Record<string, unknown>. Asserting full assignability would therefore
 * force every component to re-narrow types it already handles correctly, which
 * is a larger change than this guard is worth and one that risks playback code.
 *
 * What this DOES catch is the drift that actually bites: the backend adding or
 * renaming a field the frontend never learns about. That is what happened with
 * Tags/TagItems, where a section silently never rendered.
 */
type FieldsBackendSendsThatClientIgnores = Exclude<
  keyof Generated.LibraryItem,
  keyof LibraryItem
>
type _NoUnknownLibraryItemFields = Satisfies<never, FieldsBackendSendsThatClientIgnores>

type _SearchGroupKeys = Satisfies<never, Exclude<keyof Generated.SearchGroup, keyof SearchGroup>>
type _GroupedSearchKeys = Satisfies<
  never,
  Exclude<keyof Generated.GroupedSearchResponse, keyof GroupedSearchResponse>
>
type _ItemChildrenKeys = Satisfies<
  never,
  Exclude<keyof Generated.ItemChildrenResponse, keyof ItemChildrenResponse>
>
type _ItemSectionKeys = Satisfies<
  never,
  Exclude<keyof Generated.ItemSectionResponse, keyof ItemSectionResponse>
>
type _PlaylistListKeys = Satisfies<
  never,
  Exclude<keyof Generated.PlaylistListResponse, keyof PlaylistListResponse>
>

type KeyDrift<Actual, Expected extends PropertyKey> =
  Exclude<keyof Actual, Expected> | Exclude<Expected, keyof Actual>

type MediaItemProjectionKeys =
  | 'id' | 'name' | 'kind' | 'collection_kind' | 'overview' | 'runtime_seconds'
  | 'production_year' | 'parent_id' | 'series_id' | 'series_name' | 'season_id'
  | 'season_name' | 'index_number' | 'parent_index_number' | 'is_folder'
  | 'is_playable' | 'is_browsable' | 'has_primary_image' | 'backdrop_count'
  | 'primary_image_aspect_ratio' | 'user_state' | 'media_source_count'
type MediaDetailsProjectionKeys = MediaItemProjectionKeys
  | 'tagline' | 'genres' | 'tags' | 'people' | 'studios' | 'official_rating'
  | 'community_rating' | 'critic_rating'

type _V2MediaItemProjection = Satisfies<
  never, KeyDrift<Generated.MediaItemV2, MediaItemProjectionKeys>
>
type _V2MediaDetailsProjection = Satisfies<
  never, KeyDrift<Generated.MediaItemDetailsV2, MediaDetailsProjectionKeys>
>
type _V2UserStateProjection = Satisfies<never, KeyDrift<
  Generated.UserMediaStateV2,
  'playback_position_seconds' | 'played_percentage' | 'played' | 'favorite'
>>
type _V2PersonProjection = Satisfies<
  never, KeyDrift<Generated.PersonV2, 'id' | 'name' | 'kind'>
>
type _V2PageProjection = Satisfies<
  never, KeyDrift<Generated.MediaPageV2, 'items' | 'total' | 'start'>
>
type _V2SectionProjection = Satisfies<
  never, KeyDrift<Generated.MediaSectionV2, 'section' | 'items'>
>
type _V2StreamsProjection = Satisfies<never, KeyDrift<
  Generated.StreamCatalogV2,
  'audio' | 'subtitles' | 'media_source_id' | 'versions'
>>
type _V2AudioProjection = Satisfies<never, KeyDrift<
  Generated.AudioStreamV2,
  'index' | 'language' | 'display_language' | 'codec' | 'channels' | 'is_default' | 'title'
>>
type _V2SubtitleProjection = Satisfies<never, KeyDrift<
  Generated.SubtitleStreamV2,
  | 'index' | 'language' | 'display_language' | 'codec' | 'is_default' | 'is_forced'
  | 'is_external' | 'is_text' | 'is_image' | 'title'
>>
type _V2MediaVersionProjection = Satisfies<never, KeyDrift<
  Generated.MediaVersionV2,
  'id' | 'name' | 'container' | 'runtime_seconds'
>>
type _V2LoginContract = Satisfies<AuthResponse, Generated.LoginResponseV2>
type _V2AuthStatusContract = Satisfies<AuthResponse, Generated.AuthStatusV2>
type _V2LogoutContract = Satisfies<SuccessResponse, Generated.LogoutResponseV2>
type _V2MediaServerInfo = Satisfies<never, KeyDrift<
  Generated.MediaServerInfoV2,
  'media_server_type' | 'display_name' | 'capabilities'
>>
type _V2MediaServerCapabilities = Satisfies<
  never, KeyDrift<Generated.MediaServerCapabilitiesV2, 'filter_controls'>
>

export type {
  _FilterOption,
  _FilterControl,
  _FilterOptions,
  _LibraryPrefixes,
  _NoUnknownLibraryItemFields,
  _SearchGroupKeys,
  _GroupedSearchKeys,
  _ItemChildrenKeys,
  _ItemSectionKeys,
  _PlaylistListKeys,
  _V2AudioProjection,
  _V2AuthStatusContract,
  _V2LoginContract,
  _V2LogoutContract,
  _V2MediaDetailsProjection,
  _V2MediaItemProjection,
  _V2MediaServerCapabilities,
  _V2MediaServerInfo,
  _V2MediaVersionProjection,
  _V2PageProjection,
  _V2PersonProjection,
  _V2SectionProjection,
  _V2StreamsProjection,
  _V2SubtitleProjection,
  _V2UserStateProjection,
}
