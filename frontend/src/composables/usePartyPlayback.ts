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

export function usePartyPlayback(socket: SocketStore) {
  const registrations: Registration[] = []
  const timeouts = new Set<ReturnType<typeof setTimeout>>()
  const intervals = new Set<ReturnType<typeof setInterval>>()

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
    for (const timeout of timeouts) clearTimeout(timeout)
    for (const interval of intervals) clearInterval(interval)
    timeouts.clear()
    intervals.clear()
  }

  function schedule(callback: () => void, delay: number) {
    const timeout = setTimeout(() => {
      timeouts.delete(timeout)
      callback()
    }, delay)
    timeouts.add(timeout)
    return timeout
  }

  function cancel(timeout: ReturnType<typeof setTimeout> | null) {
    if (timeout === null) return
    clearTimeout(timeout)
    timeouts.delete(timeout)
  }

  function startInterval(callback: () => void, delay: number) {
    const interval = setInterval(callback, delay)
    intervals.add(interval)
    return interval
  }

  onUnmounted(dispose)
  return { on, schedule, cancel, startInterval, dispose }
}
