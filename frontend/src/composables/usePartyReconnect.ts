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
  // Whether the next `connect` event is a reconnect rather than this
  // page's first connection. That is a property of the socket, not of this
  // component, which is why it is seeded from the store in `attach`.
  //
  // It used to be a plain `let ... = false`, reset on every mount. A
  // remount therefore made the next genuine reconnect look like the
  // initial connect, so it was swallowed and no `join_party` was sent. The
  // member was then absent from the party server-side while the UI still
  // showed them joined, which is the worst version of this failure because
  // nothing on screen contradicts it.
  let nextConnectIsRejoin = false

  const rejoin = () => {
    if (!nextConnectIsRejoin) {
      nextConnectIsRejoin = true
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
    // `hasEverConnected` is documented in the socket store for exactly
    // this: telling a cold connect apart from a reconnect. If the socket
    // has connected before we attached, this component missed that initial
    // connect, so any connect event we do see is a reconnect and needs a
    // rejoin. Reading `connected` instead would be wrong, because a
    // remount during an outage is disconnected yet still owes a rejoin.
    nextConnectIsRejoin = socket.hasEverConnected
    socket.off('connect', rejoin)
    socket.on('connect', rejoin)
  }

  function dispose() {
    socket.off('connect', rejoin)
  }

  onUnmounted(dispose)
  return { attach, dispose }
}
