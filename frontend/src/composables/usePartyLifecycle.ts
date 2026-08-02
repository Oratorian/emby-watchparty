import { onUnmounted } from 'vue'
import type { ServerToClientEvents } from '@/types/socket'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type Registration = {
  [Event in keyof ServerToClientEvents]: {
    event: Event
    handler: ServerToClientEvents[Event]
  }
}[keyof ServerToClientEvents]

export function usePartyLifecycle(socket: SocketStore) {
  const registrations: Registration[] = []

  function on<Event extends keyof ServerToClientEvents>(
    event: Event,
    handler: ServerToClientEvents[Event],
  ) {
    socket.on(event, handler)
    registrations.push({ event, handler } as Registration)
  }

  function dispose() {
    for (const registration of registrations.splice(0)) {
      socket.off(registration.event, registration.handler)
    }
  }

  onUnmounted(dispose)
  return { on, dispose }
}
