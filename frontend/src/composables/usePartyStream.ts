import { nextTick, onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { LibraryItem, PlaybackSelection, StreamsResponse } from '@/api/client'
import type { usePartyStore } from '@/stores/party'
import { getClientId } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

// What the pre-playback "Off" option sends, and what the party then reports
// back in video_selected. A real subtitle stream never carries index -1, so
// looking it up returns undefined and reads as "nothing chosen" unless it is
// checked for first. The in-player control strip already special-cases it in
// changeTextSubtitle, which is why that selector always behaved.
const NO_SUBTITLE = -1

interface PendingVersionPick {
  item: LibraryItem
  startSeconds: number
  versions: StreamsResponse['versions']
}

interface ResumePromptState {
  item: LibraryItem
  resumeSeconds: number
  runTimeSeconds: number | null
}

export function usePartyStream(
  socket: SocketStore,
  party: PartyStore,
  onSelectionEmitted: () => void,
  videoElement: () => HTMLVideoElement | null,
) {
  const reloading = ref(false)
  const versionPickerState = ref<PendingVersionPick | null>(null)
  const resumePromptState = ref<ResumePromptState | null>(null)
  let subtitleController: AbortController | null = null
  let selectionController: AbortController | null = null
  let lastSubtitlePreloadKey: string | null = null
  const selectedTextSubIndex = ref<number | null>(null)
  const stopStreamWatch = watch(() => party.myStreamUrl, (url, previousUrl) => {
    if (url && url !== previousUrl) reloading.value = true
  })

  function signalReady() {
    if (!party.partyId) return
    reloading.value = false
    socket.emit('stream_ready', { party_id: party.partyId })
  }

  function replaceController(current: AbortController | null): AbortController {
    current?.abort()
    return new AbortController()
  }

  async function loadSubtitleStreams(
    itemId: string,
    mediaSourceId?: string,
  ): Promise<StreamsResponse> {
    subtitleController = replaceController(subtitleController)
    return api.itemStreams(itemId, mediaSourceId, subtitleController.signal)
  }

  async function loadSelectionStreams(itemId: string): Promise<StreamsResponse> {
    selectionController = replaceController(selectionController)
    return api.itemStreams(itemId, undefined, selectionController.signal)
  }

  function emitSelection(
    item: LibraryItem,
    mediaSourceId?: string,
    startSeconds = 0,
    options?: Partial<PlaybackSelection>,
  ) {
    if (!party.partyId) return
    const selectionId = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const startMode = options?.resumeMode || (startSeconds > 0 ? 'resume' : 'start_over')
    party.beginVideoSelection({
      selection_id: selectionId,
      item_id: item.Id,
      title: item.Name,
      overview: item.Overview || '',
      status: 'preparing',
      selected_by: getClientId(),
      selected_by_username: party.username || 'Someone',
      production_year: item.ProductionYear ?? null,
      run_time_seconds: item.RunTimeTicks ? Number(item.RunTimeTicks) / 10_000_000 : null,
      item_type: item.Type ?? null,
      series_name: item.SeriesName ?? null,
      season_number: item.ParentIndexNumber ?? null,
      episode_number: item.IndexNumber ?? null,
      started_at: new Date().toISOString(),
      error: null,
    })
    onSelectionEmitted()
    socket.emit('select_video', {
      party_id: party.partyId,
      selection_id: selectionId,
      item_id: item.Id,
      item_name: item.Name,
      item_overview: item.Overview || '',
      production_year: item.ProductionYear,
      run_time_seconds: item.RunTimeTicks ? Number(item.RunTimeTicks) / 10_000_000 : undefined,
      item_type: item.Type,
      series_name: item.SeriesName,
      season_number: item.ParentIndexNumber,
      episode_number: item.IndexNumber,
      quality: options?.quality || '1080p-high',
      media_source_id: mediaSourceId,
      start_seconds: startSeconds,
      audio_index: options?.audioIndex,
      subtitle_index: options?.subtitleIndex,
      resume_mode: startMode,
      binge: options?.binge,
    })
  }

  async function continueSelection(item: LibraryItem, startSeconds: number) {
    let versions: StreamsResponse['versions'] = []
    try {
      const streams = await loadSelectionStreams(item.Id)
      versions = streams.versions || []
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
    }
    if (versions.length > 1) {
      versionPickerState.value = { item, versions, startSeconds }
      return
    }
    emitSelection(item, undefined, startSeconds)
  }

  async function selectVideo(input: LibraryItem | PlaybackSelection) {
    if (!party.partyId) return
    if ('item' in input) {
      emitSelection(input.item, input.mediaSourceId, input.startSeconds, input)
      return
    }
    const item = input
    const positionTicks = Number(item.UserData?.PlaybackPositionTicks ?? 0)
    if (positionTicks > 0) {
      resumePromptState.value = {
        item,
        resumeSeconds: positionTicks / 10_000_000,
        runTimeSeconds: item.RunTimeTicks ? Number(item.RunTimeTicks) / 10_000_000 : null,
      }
      return
    }
    await continueSelection(item, 0)
  }

  function resumeSelection() {
    const pending = resumePromptState.value
    resumePromptState.value = null
    if (pending) void continueSelection(pending.item, pending.resumeSeconds)
  }

  function startSelectionOver() {
    const pending = resumePromptState.value
    resumePromptState.value = null
    if (pending) void continueSelection(pending.item, 0)
  }

  function cancelResume() {
    resumePromptState.value = null
  }

  function pickVersion(mediaSourceId: string) {
    const pending = versionPickerState.value
    versionPickerState.value = null
    if (!pending) return
    let startSeconds = pending.startSeconds
    const picked = pending.versions.find((version) => version.id === mediaSourceId)
    if (picked?.run_time_ticks && startSeconds > 0) {
      const versionRuntime = Number(picked.run_time_ticks) / 10_000_000
      if (startSeconds > Math.max(0, versionRuntime - 5)) startSeconds = 0
    }
    emitSelection(pending.item, mediaSourceId, startSeconds)
  }

  function cancelVersionPick() {
    versionPickerState.value = null
  }

  const stopSubtitleWatch = watch(
    () => {
      const video = party.currentVideo
      return [video?.item_id, video?.media_source_id, party.myStreamUrl] as const
    },
    async ([itemId, mediaSourceId, streamUrl]) => {
      if (!itemId || !mediaSourceId || !streamUrl) return
      const key = `${itemId}:${mediaSourceId}:${streamUrl}`
      if (key === lastSubtitlePreloadKey) return
      const previousItem = lastSubtitlePreloadKey?.split(':')[0] ?? null
      const isNewItem = previousItem !== itemId
      lastSubtitlePreloadKey = key
      if (isNewItem) selectedTextSubIndex.value = null

      await nextTick()
      const video = videoElement()
      if (!video) return
      video.querySelectorAll('track').forEach((track) => track.remove())

      try {
        const streams = await loadSubtitleStreams(itemId, mediaSourceId)
        if (lastSubtitlePreloadKey !== key) return
        video.querySelectorAll('track').forEach((track) => track.remove())
        const textSubtitles = streams.subtitles.filter(
          (stream) => !stream.isPGS && stream.isTextSubtitleStream,
        )
        if (isNewItem) {
          // The party's own choice wins over the source's default. The detail
          // view can pick a text subtitle for everyone before playback starts,
          // and seeding only from isDefault discarded it: the selection reached
          // the backend, but no viewer ever displayed the track.
          //
          // -1 is "Off", chosen deliberately, and is not the same as "nothing
          // chosen". No subtitle stream carries index -1, so running it through
          // find() returns undefined and the ?? below used to substitute the
          // source's default track: picking Off started the episode with
          // subtitles on, and the player's CC control showed the first track as
          // active. Treat it as a decision, not a failed lookup.
          const partyIndex = party.currentVideo?.subtitle_index ?? null
          if (partyIndex === NO_SUBTITLE) {
            selectedTextSubIndex.value = null
          } else {
            const partyChoice = partyIndex === null
              ? undefined
              : textSubtitles.find((stream) => stream.index === partyIndex)
            const defaultSubtitle = partyChoice ?? textSubtitles.find((stream) => stream.isDefault)
            if (defaultSubtitle) selectedTextSubIndex.value = defaultSubtitle.index
          }
        }
        const targetIndex = selectedTextSubIndex.value
        for (const subtitle of textSubtitles) {
          const track = document.createElement('track')
          track.kind = 'subtitles'
          let label = subtitle.displayLanguage || subtitle.language || 'Unknown'
          if (subtitle.title) label += ` (${subtitle.title})`
          if (subtitle.isForced) label += ' [Forced]'
          if (subtitle.isExternal) label += ' [External]'
          track.label = label
          track.srclang = subtitle.language || 'und'
          track.src = api.subtitleUrl(itemId, mediaSourceId, subtitle.index)
          video.appendChild(track)
          if (track.track) {
            track.track.mode = subtitle.index === targetIndex ? 'showing' : 'hidden'
          }
        }
        if (targetIndex !== null) {
          video.addEventListener('loadeddata', () => {
            for (const track of Array.from(video.querySelectorAll('track'))) {
              const match = track.src.match(/\/subtitles\/[^/]+\/(\d+)/)
              const index = match?.[1] ? parseInt(match[1], 10) : null
              track.track.mode = index === targetIndex ? 'showing' : 'hidden'
            }
          }, { once: true })
        }
      } catch {
        // A stale/failed subtitle request must not disturb video playback.
      }
    },
  )

  function changeTextSubtitle(payload: { index: number; url: string | null }) {
    selectedTextSubIndex.value = payload.index >= 0 && payload.url ? payload.index : null
    const video = videoElement()
    if (!video) return
    if (payload.index === -1 || !payload.url) {
      for (const track of Array.from(video.textTracks)) track.mode = 'hidden'
      return
    }
    const elements = Array.from(video.querySelectorAll('track'))
    const target = elements.find((track) => track.src.endsWith(payload.url!))
    if (target) {
      for (const track of Array.from(video.textTracks)) {
        track.mode = track === target.track ? 'showing' : 'hidden'
      }
      return
    }
    const track = document.createElement('track')
    track.kind = 'subtitles'
    track.label = 'Subtitles'
    track.srclang = 'und'
    track.src = payload.url
    track.default = true
    const showTrack = () => {
      for (const textTrack of Array.from(video.textTracks)) {
        textTrack.mode = textTrack === track.track ? 'showing' : 'disabled'
      }
    }
    track.addEventListener('load', showTrack, { once: true })
    video.appendChild(track)
    showTrack()
  }

  onUnmounted(() => {
    stopStreamWatch()
    stopSubtitleWatch()
    subtitleController?.abort()
    selectionController?.abort()
  })
  return {
    reloading,
    versionPickerState,
    resumePromptState,
    signalReady,
    loadSubtitleStreams,
    changeTextSubtitle,
    selectVideo,
    resumeSelection,
    startSelectionOver,
    cancelResume,
    pickVersion,
    cancelVersionPick,
  }
}
