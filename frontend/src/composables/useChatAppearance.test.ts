import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatAppearance } from './useChatAppearance'

const KEY = 'watchparty-chat-appearance'
beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('chat appearance preferences', () => {
  it('uses defaults without writing a preference until the viewer changes it', () => {
    const chat = useChatAppearance()
    expect(chat.font.value).toBe('default')
    expect(chat.size.value).toBe(14)
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('remembers a chosen font and size and resets both together', () => {
    const chat = useChatAppearance()
    chat.font.value = 'oxanium'
    chat.size.value = 19
    const restored = useChatAppearance()
    expect(restored.font.value).toBe('oxanium')
    expect(restored.style.value['--chat-font-size']).toBe('19px')
    expect(restored.style.value['--chat-font-family']).toContain('EWP Oxanium')
    restored.reset()
    const reset = useChatAppearance()
    expect(reset.font.value).toBe('default')
    expect(reset.size.value).toBe(14)
  })

  it.each(['invalid JSON', 'null', '[]', '{"font":"untrusted","size":999}', '{"size":"20"}'])(
    'ignores invalid persisted values: %s', (value) => {
      localStorage.setItem(KEY, value)
      const chat = useChatAppearance()
      expect(chat.font.value).toBe('default')
      expect(chat.size.value).toBe(14)
      expect(localStorage.getItem(KEY)).toBe(value)
    },
  )

  it('recovers valid fields independently', () => {
    localStorage.setItem(KEY, '{"font":"rajdhani","size":-1}')
    const chat = useChatAppearance()
    expect(chat.font.value).toBe('rajdhani')
    expect(chat.size.value).toBe(14)
  })

  it('rejects invalid updates without replacing the current preference', () => {
    const chat = useChatAppearance()
    chat.size.value = 20
    for (const value of [11, 25, 14.5, NaN, Infinity]) chat.size.value = value
    chat.font.value = 'url(https://invalid.test)' as never
    expect(chat.font.value).toBe('default')
    expect(chat.size.value).toBe(20)
  })

  it('keeps settings usable when browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const chat = useChatAppearance()
    expect(() => {
      chat.font.value = 'space-grotesk'
      chat.size.value = 18
    }).not.toThrow()
    expect(chat.style.value['--chat-font-family']).toContain('EWP Space Grotesk')
    expect(chat.size.value).toBe(18)
  })
})
