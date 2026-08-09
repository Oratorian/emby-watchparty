import { describe, expect, it, vi } from 'vitest'
import { usePartyChat } from './usePartyChat'

function harness() {
  const handlers = new Map<string, (data: never) => void>()
  const socket = {
    emit: vi.fn(),
    on: vi.fn((event: string, handler: (data: never) => void) => handlers.set(event, handler)),
    off: vi.fn(),
  }
  const chat = usePartyChat(socket as never, { partyId: 'ABC123' } as never)
  chat.attach()
  return { handlers, socket, chat }
}

function refuse(
  handlers: Map<string, (data: never) => void>,
  requestId: string,
  retryAfter = 2,
) {
  handlers.get('rate_limited')?.({
    action: 'chat',
    message: 'Message not sent. Try again in 2 seconds.',
    retry_after: retryAfter,
    request_id: requestId,
  } as never)
}

describe('usePartyChat', () => {
  it('restores a rate-limited draft without resending it', () => {
    vi.useFakeTimers()
    const { handlers, socket, chat } = harness()
    chat.input.value = 'please keep this'

    chat.send()
    const payload = socket.emit.mock.calls[0]?.[1]
    expect(payload.request_id).toEqual(expect.any(String))
    expect(chat.input.value).toBe('')

    refuse(handlers, payload.request_id)

    expect(chat.input.value).toBe('please keep this')
    expect(chat.rateLimitError.value).toContain('not sent')
    expect(chat.rateLimitRetryAfter.value).toBe(2)

    // The half this test is named for: while the countdown runs, send() must
    // refuse. Without these two lines the guard in send() can be deleted and
    // the suite stays green.
    chat.send()
    expect(socket.emit).toHaveBeenCalledTimes(1)
    expect(chat.input.value).toBe('please keep this')

    vi.advanceTimersByTime(2000)
    expect(chat.rateLimitRetryAfter.value).toBe(0)
    chat.send()
    expect(socket.emit).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('clears the rate-limit alert when the countdown expires', () => {
    vi.useFakeTimers()
    const { handlers, socket, chat } = harness()
    chat.input.value = 'hello'
    chat.send()

    refuse(handlers, socket.emit.mock.calls[0]?.[1].request_id)
    expect(chat.rateLimitError.value).toContain('not sent')

    vi.advanceTimersByTime(2000)
    expect(chat.rateLimitRetryAfter.value).toBe(0)
    // Left set, the alert outlived the countdown that explained it and stayed
    // until the next successful send: a permanent false error for a user who
    // simply stops typing.
    expect(chat.rateLimitError.value).toBeNull()
    vi.useRealTimers()
  })

  it('queues a refused draft instead of merging it into a different message', () => {
    vi.useFakeTimers()
    const { handlers, socket, chat } = harness()
    chat.input.value = 'on my way'
    chat.send()
    // The user keeps typing while the send is still in flight.
    chat.input.value = 'brb'

    refuse(handlers, socket.emit.mock.calls[0]?.[1].request_id)

    expect(chat.input.value).toBe('brb')
    expect(chat.unsentDrafts.value).toEqual(['on my way'])

    // Not restorable while the composer holds something else.
    chat.restoreDraft(0)
    expect(chat.unsentDrafts.value).toEqual(['on my way'])

    chat.input.value = ''
    chat.restoreDraft(0)
    expect(chat.input.value).toBe('on my way')
    expect(chat.unsentDrafts.value).toEqual([])
    vi.useRealTimers()
  })

  it('keeps two refused drafts in the order they were written', () => {
    vi.useFakeTimers()
    const { handlers, socket, chat } = harness()
    chat.input.value = 'first message'
    chat.send()
    chat.input.value = 'second message'
    chat.send()

    const first = socket.emit.mock.calls[0]?.[1].request_id
    const second = socket.emit.mock.calls[1]?.[1].request_id
    expect(first).not.toBe(second)

    refuse(handlers, first)
    refuse(handlers, second)

    // Previously both were concatenated into the composer, and because each
    // arrival prepended, they came out reversed as "second message first
    // message" -- one message the user never wrote.
    expect(chat.input.value).toBe('first message')
    expect(chat.unsentDrafts.value).toEqual(['second message'])
    vi.useRealTimers()
  })
})
