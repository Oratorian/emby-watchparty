import { onUnmounted } from 'vue'
import type { useAvatarStore } from '@/stores/avatar'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>
type AvatarStore = ReturnType<typeof useAvatarStore>

export function usePartyReconnect(
  socket: SocketStore,
  party: PartyStore,
  avatar: AvatarStore,
  clientId: () => string,
) {
  let initialConnectSeen = false

  const rejoin = () => {
    if (!initialConnectSeen) {
      initialConnectSeen = true
      return
    }
    if (!party.partyId || !party.username) return
    socket.emit('join_party', {
      party_id: party.partyId,
      username: party.username,
      client_id: clientId(),
      avatar_uuid: avatar.uuid,
    })
  }

  function attach() {
    socket.off('connect', rejoin)
    socket.on('connect', rejoin)
  }

  function dispose() {
    socket.off('connect', rejoin)
  }

  onUnmounted(dispose)
  return { attach, dispose }
}
