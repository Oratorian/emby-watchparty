import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import ShowBackgroundPreview from './ShowBackgroundPreview.vue'

const { FakeHls, instances } = vi.hoisted(() => {
  const instances: any[] = []
  class FakeHls {
    static isSupported = () => true
    static Events = { MEDIA_ATTACHED: 'attached', MANIFEST_PARSED: 'parsed', ERROR: 'error' }
    listeners = new Map<string, (event: string, data?: unknown) => void>()
    loadSource = vi.fn()
    startLoad = vi.fn()
    stopLoad = vi.fn()
    destroy = vi.fn()
    attachMedia = vi.fn((video: HTMLVideoElement) => {
      video.src = 'blob:isolated-preview'
      this.emit('attached')
    })
    constructor() { instances.push(this) }
    on(event: string, callback: (event: string, data?: unknown) => void) { this.listeners.set(event, callback) }
    once(event: string, callback: (event: string, data?: unknown) => void) { this.listeners.set(event, callback) }
    emit(event: string, data?: unknown) { this.listeners.get(event)?.(event, data) }
  }
  return { FakeHls, instances }
})
vi.mock('hls.js', () => ({ default: FakeHls }))

let intersection: IntersectionObserverCallback
let motion: { matches: boolean; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> }
let visibility: ReturnType<typeof vi.spyOn>
const wrappers: VueWrapper[] = []
const response = (id = 'preview-1') => ({
  preview_id: id, url: '/hls/preview/master.m3u8', duration_seconds: 120, start_seconds: 240, expires_in: 180,
})

beforeEach(() => {
  localStorage.clear()
  instances.length = 0
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.spyOn(api, 'startShowPreview').mockResolvedValue(response())
  vi.spyOn(api, 'stopShowPreview').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  motion = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', vi.fn(() => motion))
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { intersection = callback }
    observe() {}
    disconnect() {}
  })
})
afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  Reflect.deleteProperty(navigator, 'connection')
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function intersect(visible: boolean) {
  intersection([{ isIntersecting: visible, intersectionRatio: visible ? 1 : 0 } as IntersectionObserverEntry], {} as IntersectionObserver)
}

async function mountPreview() {
  const wrapper = mount(ShowBackgroundPreview, { props: { itemId: 'series-1' } })
  wrappers.push(wrapper)
  await flushPromises()
  intersect(true)
  return wrapper
}

async function prepare(wrapper: VueWrapper) {
  await vi.advanceTimersByTimeAsync(800)
  await flushPromises()
  const hls = instances.at(-1)!
  expect(hls).toBeTruthy()
  hls.emit('parsed')
  await flushPromises()
  return { hls, video: wrapper.get<HTMLVideoElement>('video') }
}

describe('show background previews', () => {
  it('waits until visible, then starts muted without party events or saved sound preferences', async () => {
    localStorage.setItem('watchparty-preview-muted', 'false')
    const wrapper = await mountPreview()
    await vi.advanceTimersByTimeAsync(799)
    expect(api.startShowPreview).not.toHaveBeenCalled()
    const { video } = await prepare(wrapper)
    expect(api.startShowPreview).toHaveBeenCalledWith('series-1', { signal: expect.any(AbortSignal) })
    expect(video.element.muted).toBe(true)
    expect(video.classes()).not.toContain('is-playing')
    await video.trigger('playing')
    expect(video.classes()).toContain('is-playing')
    expect(wrapper.emitted()).not.toHaveProperty('play')
    expect(wrapper.emitted()).not.toHaveProperty('ready')
  })

  it('shows an explicit Play action if muted autoplay is blocked', async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException('blocked', 'NotAllowedError'))
    const wrapper = await mountPreview()
    const { video } = await prepare(wrapper)
    expect(wrapper.text()).toContain('Play preview')
    expect(video.element.muted).toBe(true)
    expect(video.classes()).not.toContain('is-playing')
    await wrapper.findAll('button').find(button => button.text() === 'Play preview')!.trigger('click')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2)
    await video.trigger('playing')
    expect(wrapper.text()).toContain('Pause preview')
    expect(video.element.muted).toBe(true)
  })

  it('releases an unsupported stream instead of treating it as blocked autoplay', async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException('unsupported', 'NotSupportedError'))
    const wrapper = await mountPreview()
    const { video, hls } = await prepare(wrapper)
    expect(api.stopShowPreview).toHaveBeenCalledWith('preview-1', { keepalive: false })
    expect(hls.destroy).toHaveBeenCalledTimes(1)
    expect(video.element.hasAttribute('src')).toBe(false)
    expect(video.classes()).not.toContain('is-playing')
    expect(wrapper.text()).toContain('Play preview')
    expect(wrapper.text()).not.toContain('Mute preview')
  })

  it('unmutes on demand, preserves that choice on pause/resume, and mutes the next show again', async () => {
    const wrapper = await mountPreview()
    const { video, hls } = await prepare(wrapper)
    await video.trigger('playing')
    await wrapper.findAll('button').find(button => button.text() === 'Unmute preview')!.trigger('click')
    expect(video.element.muted).toBe(false)
    expect(localStorage.getItem('watchparty-preview-muted')).toBeNull()
    await wrapper.findAll('button').find(button => button.text() === 'Pause preview')!.trigger('click')
    expect(hls.stopLoad).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Play preview')
    expect(api.stopShowPreview).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(button => button.text() === 'Play preview')!.trigger('click')
    expect(video.element.muted).toBe(false)
    await video.trigger('playing')
    vi.mocked(api.startShowPreview).mockResolvedValueOnce(response('preview-2'))
    await wrapper.setProps({ itemId: 'series-2' })
    const prepared = await prepare(wrapper)
    expect(prepared.video.element.muted).toBe(true)
    expect(api.startShowPreview).toHaveBeenLastCalledWith('series-2', { signal: expect.any(AbortSignal) })
  })

  it.each(['hidden', 'outside viewport', 'room starts', 'pagehide', 'unmount'])(
    'releases its stream and removes video media on %s', async (reason) => {
      const wrapper = await mountPreview()
      const { video, hls } = await prepare(wrapper)
      await video.trigger('playing')
      if (reason === 'hidden') {
        visibility.mockReturnValue('hidden')
        document.dispatchEvent(new Event('visibilitychange'))
      } else if (reason === 'outside viewport') intersect(false)
      else if (reason === 'room starts') await wrapper.setProps({ active: false })
      else if (reason === 'pagehide') window.dispatchEvent(new Event('pagehide'))
      else wrapper.unmount()
      await nextTick()
      expect(hls.destroy).toHaveBeenCalledTimes(1)
      expect(video.element.hasAttribute('src')).toBe(false)
      expect(api.stopShowPreview).toHaveBeenCalledWith('preview-1', {
        keepalive: ['hidden', 'pagehide', 'unmount'].includes(reason),
      })
      await vi.advanceTimersByTimeAsync(1000)
      expect(api.startShowPreview).toHaveBeenCalledTimes(1)
    },
  )

  it('releases a late response after the title changes even when abort is ignored', async () => {
    let resolve!: (value: ReturnType<typeof response>) => void
    vi.mocked(api.startShowPreview).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = await mountPreview()
    await vi.advanceTimersByTimeAsync(800)
    await flushPromises()
    const signal = vi.mocked(api.startShowPreview).mock.calls[0]![1]!.signal!
    await wrapper.setProps({ itemId: 'series-2' })
    expect(signal.aborted).toBe(true)
    resolve(response('old-preview'))
    await flushPromises()
    expect(api.stopShowPreview).toHaveBeenCalledWith('old-preview', { keepalive: false })
    expect(instances).toHaveLength(0)
  })

  it('ends after two minutes relative to the first frame, even with offset timestamps', async () => {
    const wrapper = await mountPreview()
    const { video } = await prepare(wrapper)
    video.element.currentTime = 240
    await video.trigger('playing')
    video.element.currentTime = 359.9
    await video.trigger('timeupdate')
    expect(api.stopShowPreview).not.toHaveBeenCalled()
    video.element.currentTime = 360
    await video.trigger('timeupdate')
    expect(api.stopShowPreview).toHaveBeenCalledTimes(1)
    expect(video.classes()).not.toContain('is-playing')
    expect(wrapper.text()).toContain('Play preview')
  })

  it.each(['reduced motion', 'save data'])('requires manual play for %s', async (preference) => {
    if (preference === 'reduced motion') motion.matches = true
    else Object.defineProperty(navigator, 'connection', { configurable: true, value: Object.assign(new EventTarget(), { saveData: true }) })
    const wrapper = await mountPreview()
    await vi.advanceTimersByTimeAsync(1000)
    expect(api.startShowPreview).not.toHaveBeenCalled()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(api.startShowPreview).toHaveBeenCalledTimes(1)
  })

  it('falls back to the backdrop and releases the lease on a fatal HLS error', async () => {
    const wrapper = await mountPreview()
    const { hls, video } = await prepare(wrapper)
    await video.trigger('playing')
    hls.emit('error', { fatal: true })
    await nextTick()
    expect(api.stopShowPreview).toHaveBeenCalledTimes(1)
    expect(hls.destroy).toHaveBeenCalledTimes(1)
    expect(video.classes()).not.toContain('is-playing')
  })

  it('ignores callbacks belonging to a released HLS instance after replay starts', async () => {
    const wrapper = await mountPreview()
    const first = await prepare(wrapper)
    await first.video.trigger('ended')
    vi.mocked(api.startShowPreview).mockResolvedValueOnce(response('preview-2'))
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const second = instances.at(-1)!
    const loads = second.loadSource.mock.calls.length
    first.hls.emit('attached')
    first.hls.emit('error', { fatal: true })
    await nextTick()
    expect(second.loadSource).toHaveBeenCalledTimes(loads)
    expect(second.destroy).not.toHaveBeenCalled()
    expect(api.stopShowPreview).not.toHaveBeenCalledWith('preview-2', expect.anything())
  })
})
