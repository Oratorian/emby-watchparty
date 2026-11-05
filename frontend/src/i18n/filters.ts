import type { FilterControl, FilterOption } from '@/api/client'
import { t } from '@/i18n'

const controlIds = new Set(["playstate", "favorite", "duplicates", "community_rating", "critic_rating", "genre", "studio", "tag", "year", "official_rating", "container", "video_codec", "audio_codec", "audio_layout", "subtitle_codec", "video_type", "resolution", "is_3d", "subtitles", "trailers", "extras", "theme_songs", "theme_videos", "locked", "overview", "missing_provider_ids"])
const withWithoutIds = new Set(['subtitles', 'trailers', 'extras', 'theme_songs', 'theme_videos', 'overview'])
const searchGroups = new Set(['movies', 'series', 'episodes', 'people', 'collections'])
const mediaKinds = new Set(["Movie", "Series", "Episode", "Season", "BoxSet", "Video", "Folder", "CollectionFolder", "Playlist", "Person", "Recording", "TvChannel"])

export function filterLabel(control: FilterControl): string {
  return controlIds.has(control.id) ? t(`library.filter_${control.id}`) : control.label
}

export function filterOptionLabel(control: FilterControl, option: FilterOption): string {
  if (option.value === 'any' && (control.id === 'playstate' || control.id === 'resolution' || control.id === 'locked' || withWithoutIds.has(control.id))) {
    return t('library.option_any')
  }
  if (control.id === 'playstate' && ['unplayed', 'played', 'resumable'].includes(option.value)) {
    return t(`library.option_${option.value}`)
  }
  if (withWithoutIds.has(control.id) && ['with', 'without'].includes(option.value)) {
    return t(`library.option_${option.value}`)
  }
  if (control.id === 'locked' && ['yes', 'no'].includes(option.value)) {
    return t(option.value === 'yes' ? 'library.option_with' : 'library.option_without')
  }
  if (control.id === 'official_rating' && option.value === 'Unrated') {
    return t('library.option_unrated')
  }
  if (control.id === 'video_type' && ['VideoFile', 'Bluray', 'Dvd', 'Iso'].includes(option.value)) {
    return t(`library.option_${option.value}`)
  }
  return option.label
}

export function searchGroupLabel(group: { id: string; label: string }): string {
  return searchGroups.has(group.id) ? t(`library.group_${group.id}`) : group.label
}

export function mediaKindLabel(kind: string | null | undefined): string {
  if (!kind) return ''
  return mediaKinds.has(kind) ? t(`library.type_${kind}`) : kind
}

export function qualityLabel(option: { id: string; label: string }): string {
  return option.id === 'auto' ? t('library.auto_quality') : option.label
}
