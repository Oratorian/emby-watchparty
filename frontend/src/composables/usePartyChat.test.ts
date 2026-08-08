import { describe, expect, it, vi } from 'vitest'
import { usePartyChat } from './usePartyChat'

describe('usePartyChat', () => {
  it('restores a rate-limited draft without resending it', () => {
    vi.useFakeTimers()
    const handlers = new Map<string, (data: never) => void>()
    const socket = {
      emit: vi.fn(),
      on: vi.fn((event: string, handler: (data: never) => void) => handlers.set(event, handler)),
      off: vi.fn(),
    }
    const party = { partyId: 'ABC123' }
    const chat = usePartyChat(socket as never, party as never)
    chat.attach()
    chat.input.value = 'please keep this'

    chat.send()
    const payload = socket.emit.mock.calls[0]?.[1]
    expect(payload.request_id).toEqual(expect.any(String))
    expect(chat.input.value).toBe('')

    handlers.get('rate_limited')?.({
      action: 'chat',
      message: 'Message not sent. Try again in 2 seconds.',
      retry_after: 2,
      request_id: payload.request_id,
    } as never)

    expect(chat.input.value).toBe('please keep this')
    expect(chat.rateLimitError.value).toContain('not sent')
    expect(chat.rateLimitRetryAfter.value).toBe(2)
    vi.advanceTimersByTime(2000)
    expect(chat.rateLimitRetryAfter.value).toBe(0)
    expect(socket.emit).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})
