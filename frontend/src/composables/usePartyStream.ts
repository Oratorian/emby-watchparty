import { onUnmounted, ref, watch } from 'vue'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

export function usePartyStream(socket: SocketStore, party: PartyStore) {
  const reloading = ref(false)
  const stopStreamWatch = watch(() => party.myStreamUrl, (url, previousUrl) => {
    if (url && url !== previousUrl) reloading.value = true
  })

  function signalReady() {
    if (!party.partyId) return
    reloading.value = false
    socket.emit('stream_ready', { party_id: party.partyId })
  }

  onUnmounted(stopStreamWatch)
  return { reloading, signalReady }
}
