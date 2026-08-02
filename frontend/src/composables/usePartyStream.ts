import { onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { StreamsResponse } from '@/api/client'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

export function usePartyStream(socket: SocketStore, party: PartyStore) {
  const reloading = ref(false)
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

  onUnmounted(() => {
    stopStreamWatch()
    subtitleController?.abort()
    selectionController?.abort()
  })
  return { reloading, signalReady, loadSubtitleStreams, loadSelectionStreams }
}
