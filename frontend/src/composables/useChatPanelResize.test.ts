import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatPanelResize } from './useChatPanelResize'

const STORAGE_KEY = 'watchparty-chat-width'
const wrappers: VueWrapper[] = []
const observers = new Set<() => void>()

class MockResizeObserver {
  constructor(private callback: () => void) {}
  observe() { observers.add(this.callback) }
  disconnect() { observers.delete(this.callback) }
}

async function harness() {
  let available = 1600
  let desktop = true
  const mediaListeners = new Set<() => void>()
  const media = {
    get matches() { return desktop },
    addEventListener: vi.fn((_event: string, callback: () => void) => mediaListeners.add(callback)),
    removeEventListener: vi.fn((_event: string, callback: () => void) => mediaListeners.delete(callback)),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  let resize!: ReturnType<typeof useChatPanelResize>
  const wrapper = mount(defineComponent({
    setup() {
      resize = useChatPanelResize()
      return () => h('div', [
        h('main', { ref: resize.videoArea }),
        h('aside', { ref: resize.chatPanel }),
      ])
    },
  }))
  wrappers.push(wrapper)
  await nextTick()
  vi.spyOn(resize.videoArea.value!, 'getBoundingClientRect').mockImplementation(
    () => ({ width: available - resize.width.value }) as DOMRect,
  )
  vi.spyOn(resize.chatPanel.value!, 'getBoundingClientRect').mockImplementation(
    () => ({ width: resize.width.value }) as DOMRect,
  )
  const handle = document.createElement('div')
  let captured: number | undefined
  const capture = vi.fn((id: number) => { captured = id })
  const release = vi.fn(() => { captured = undefined })
  Object.assign(handle, {
    setPointerCapture: capture,
    hasPointerCapture: (id: number) => captured === id,
    releasePointerCapture: release,
  })
  function pointer(x: number, id = 1, button = 0) {
    return {
      clientX: x, pointerId: id, button, currentTarget: handle, preventDefault: vi.fn(),
    } as unknown as PointerEvent
  }
  function keyboard(key: string) {
    const event = new KeyboardEvent('keydown', { key, cancelable: true })
    resize.resizeWithKeyboard(event)
    return event
  }
  function layout(width: number) {
    available = width
    for (const callback of observers) callback()
  }
  function drawer(open: boolean) {
    desktop = !open
    for (const callback of mediaListeners) callback()
  }
  layout(available)
  return { resize, wrapper, pointer, keyboard, layout, drawer, capture, release, media }
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
})

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  observers.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('chat width preference', () => {
  it('ignores invalid saved widths without replacing the stored value', async () => {
    for (const invalid of ['not a width', 'Infinity', '900']) {
      localStorage.setItem(STORAGE_KEY, invalid)
      const { resize, wrapper } = await harness()
      expect(resize.width.value).toBe(320)
      expect(localStorage.getItem(STORAGE_KEY)).toBe(invalid)
      wrapper.unmount()
    }
  })

  it('still resizes when storage access is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const { resize, keyboard } = await harness()
    expect(resize.width.value).toBe(320)
    expect(() => keyboard('ArrowLeft')).not.toThrow()
    expect(resize.width.value).toBe(340)
  })

  it('temporarily clamps a preference to protect video space and restores it afterward', async () => {
    localStorage.setItem(STORAGE_KEY, '540')
    const { resize, layout, keyboard } = await harness()
    layout(950) // The library leaves 950px shared by video and chat.
    expect(resize.width.value).toBe(310)
    expect(localStorage.getItem(STORAGE_KEY)).toBe('540')
    layout(1300)
    expect(resize.width.value).toBe(520)
    layout(1600)
    expect(resize.width.value).toBe(540)
    keyboard('ArrowRight')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('520')
  })

  it('lets normal typing pass through without changing the width', async () => {
    const { resize, keyboard } = await harness()
    expect(keyboard('a').defaultPrevented).toBe(false)
    expect(resize.width.value).toBe(320)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(keyboard('ArrowLeft').defaultPrevented).toBe(true)
  })
})

describe('chat resize pointer lifecycle', () => {
  it('ignores other mouse buttons and pointers while a drag is active', async () => {
    const { resize, pointer, capture } = await harness()
    resize.startResize(pointer(1000, 1, 2))
    expect(capture).not.toHaveBeenCalled()
    resize.startResize(pointer(1000))
    resize.startResize(pointer(900, 2))
    resize.moveResize(pointer(800, 2))
    resize.endResize(pointer(800, 2))
    expect(capture).toHaveBeenCalledTimes(1)
    expect(resize.width.value).toBe(320)
    expect(resize.resizing.value).toBe(true)
    resize.moveResize(pointer(900))
    expect(resize.width.value).toBe(420)
    resize.endResize(pointer(900))
    expect(resize.resizing.value).toBe(false)
  })

  it.each(['cancel', 'lost capture', 'blur', 'drawer', 'unmount'])(
    'stops resizing after %s, releases capture and ignores later moves',
    async (reason) => {
      const { resize, pointer, release, drawer, wrapper, keyboard } = await harness()
      resize.startResize(pointer(1000))
      resize.moveResize(pointer(900))
      expect(resize.width.value).toBe(420)
      if (reason === 'blur') window.dispatchEvent(new Event('blur'))
      else if (reason === 'drawer') drawer(true)
      else if (reason === 'unmount') wrapper.unmount()
      else resize.endResize(pointer(900))
      expect(resize.resizing.value).toBe(false)
      expect(release).toHaveBeenCalledTimes(1)
      resize.moveResize(pointer(700))
      expect(resize.width.value).toBe(420)
      if (reason === 'drawer') {
        resize.startResize(pointer(900))
        keyboard('ArrowLeft')
        resize.resetWidth()
        expect(resize.resizing.value).toBe(false)
        expect(resize.width.value).toBe(420)
      }
    },
  )

  it('disconnects layout and browser listeners on unmount', async () => {
    const { resize, wrapper, layout, drawer, media } = await harness()
    const remove = vi.spyOn(window, 'removeEventListener')
    wrapper.unmount()
    expect(observers.size).toBe(0)
    expect(media.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    expect(remove).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(remove).toHaveBeenCalledWith('blur', expect.any(Function))
    layout(950)
    drawer(true)
    expect(resize.width.value).toBe(320)
  })
})
