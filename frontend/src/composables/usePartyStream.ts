import { onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { LibraryItem, StreamsResponse } from '@/api/client'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

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
) {
  const reloading = ref(false)
  const versionPickerState = ref<PendingVersionPick | null>(null)
  const resumePromptState = ref<ResumePromptState | null>(null)
  let subtitleController: AbortController | null = null
  let selectionController: AbortController | null = null
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

  function emitSelection(item: LibraryItem, mediaSourceId?: string, startSeconds = 0) {
    if (!party.partyId) return
    onSelectionEmitted()
    socket.emit('select_video', {
      party_id: party.partyId,
      item_id: item.Id,
      item_name: item.Name,
      item_overview: item.Overview || '',
      quality: '1080p-high',
      media_source_id: mediaSourceId,
      start_seconds: startSeconds,
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

  async function selectVideo(item: LibraryItem) {
    if (!party.partyId) return
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

  onUnmounted(() => {
    stopStreamWatch()
    subtitleController?.abort()
    selectionController?.abort()
  })
  return {
    reloading,
    versionPickerState,
    resumePromptState,
    signalReady,
    loadSubtitleStreams,
    selectVideo,
    resumeSelection,
    startSelectionOver,
    cancelResume,
    pickVersion,
    cancelVersionPick,
  }
}
