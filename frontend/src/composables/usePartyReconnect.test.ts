import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { usePartyReconnect } from './usePartyReconnect'

type Handler = () => void

function makeSocket(hasEverConnected: boolean) {
  const handlers: Record<string, Handler[]> = {}
  return {
    hasEverConnected,
    sessionRebinding: false,
    emit: vi.fn(),
    on: vi.fn((event: string, fn: Handler) => {
      ;(handlers[event] ??= []).push(fn)
    }),
    off: vi.fn((event: string, fn: Handler) => {
      handlers[event] = (handlers[event] ?? []).filter((existing) => existing !== fn)
    }),
    fire(event: string) {
      for (const fn of [...(handlers[event] ?? [])]) fn()
    },
  }
}

function attachTo(socket: ReturnType<typeof makeSocket>) {
  const party = { partyId: 'PARTY', username: 'Alice', joinInProgress: false, sessionError: null as string | null }
  const avatar = { uuid: 'avatar-1' }
  let attach: (() => void) | undefined

  mount(
    defineComponent({
      setup() {
        const reconnect = usePartyReconnect(
          socket as never,
          party as never,
          avatar as never,
          () => 'client-1',
        )
        attach = reconnect.attach
        return () => h('div')
      },
    }),
  )

  attach?.()
  return party
}

describe('usePartyReconnect', () => {
  it('does not rejoin on the initial connect of a cold load', () => {
    const socket = makeSocket(false)
    attachTo(socket)

    socket.fire('connect')

    expect(socket.emit).not.toHaveBeenCalled()
  })

  it('rejoins when the socket drops and comes back', () => {
    const socket = makeSocket(false)
    attachTo(socket)

    socket.fire('connect') // initial
    socket.fire('connect') // genuine reconnect

    expect(socket.emit).toHaveBeenCalledWith(
      'join_party',
      expect.objectContaining({ party_id: 'PARTY', username: 'Alice' }),
    )
  })

  it('still rejoins when the component remounted after the socket connected', () => {
    // The defect. The flag was component-local and reset to false on every
    // mount, so a remount made the next genuine reconnect look like the
    // initial connect. It was swallowed, no join_party was sent, and the
    // member was absent from the party server-side while the UI still
    // showed them joined.
    const socket = makeSocket(true)
    attachTo(socket)

    socket.fire('connect')

    expect(socket.emit).toHaveBeenCalledWith(
      'join_party',
      expect.objectContaining({ party_id: 'PARTY' }),
    )
  })

  it('leaves explicit binding and its fresh handshake to the join flow', () => {
    const socket = makeSocket(true)
    const party = attachTo(socket)
    party.joinInProgress = true
    socket.fire('connect')
    party.joinInProgress = false
    socket.sessionRebinding = true
    socket.fire('connect')
    expect(socket.emit).not.toHaveBeenCalled()

    socket.sessionRebinding = false
    socket.fire('connect')
    expect(socket.emit).toHaveBeenCalledTimes(1)
  })

  it('does not bypass a failed HTTP binding on a later transport reconnect', () => {
    const socket = makeSocket(true)
    const party = attachTo(socket)
    party.sessionError = 'Could not bind session'
    socket.fire('connect')
    expect(socket.emit).not.toHaveBeenCalled()
  })
})
