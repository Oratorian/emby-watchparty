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
}
