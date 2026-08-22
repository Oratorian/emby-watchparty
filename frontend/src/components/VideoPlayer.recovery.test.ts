import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// A stand-in for hls.js that records listeners and can fire an event as many
// times as the real library would. `on` and `once` differ in exactly the way
// this regression is about, so both are modelled rather than aliased.
//
// Built inside vi.hoisted because vi.mock is lifted above the file body, so a
// plain top-level class is not initialised by the time the factory runs.
//
// MEDIA_ATTACHED is emitted ASYNCHRONOUSLY, which matters: the real library
// fires it from the MediaSource `sourceopen` handler, and the component
// registers its listener on the line after attachMedia(). A fake that emitted
// synchronously would report a listener that never ran and fail for a reason
// the production code does not have.
const { FakeHls, instances } = vi.hoisted(() => {
  const created: any[] = []

  class Fake {
    static isSupported = () => true
    static Events = {
      MEDIA_ATTACHED: 'hlsMediaAttached',
      MANIFEST_PARSED: 'hlsManifestParsed',
      ERROR: 'hlsError',
      FRAG_CHANGED: 'hlsFragChanged',
    }
    static ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' }

    loadSource = vi.fn()
    detachMedia = vi.fn()
    destroy = vi.fn()
    startLoad = vi.fn()
    attachMedia = vi.fn(() => {
      queueMicrotask(() => this.emit(Fake.Events.MEDIA_ATTACHED))
    })

    sticky = new Map<string, Array<(e: string, d?: unknown) => void>>()
    single = new Map<string, Array<(e: string, d?: unknown) => void>>()

    constructor() {
      created.push(this)
    }

    on(event: string, listener: (e: string, d?: unknown) => void) {
      this.sticky.set(event, [...(this.sticky.get(event) ?? []), listener])
    }

    once(event: string, listener: (e: string, d?: unknown) => void) {
      this.single.set(event, [...(this.single.get(event) ?? []), listener])
    }

    emit(event: string, data?: unknown) {
      for (const listener of this.sticky.get(event) ?? []) listener(event, data)
      const pending = this.single.get(event) ?? []
      this.single.delete(event)
      for (const listener of pending) listener(event, data)
    }

    /** What hls.js does on a fatal media error: detach, re-attach, resume. */
    recoverMediaError(atTime: number) {
      this.detachMedia()
      this.attachMedia()
      this.startLoad(atTime)
    }
  }

  return { FakeHls: Fake, instances: created }
})

vi.mock('hls.js', () => ({ default: FakeHls }))

import VideoPlayer from './VideoPlayer.vue'

describe('VideoPlayer error recovery', () => {
  beforeEach(() => {
    instances.length = 0
    setActivePinia(createPinia())
  })

  const mountPlayer = () =>
    mount(VideoPlayer, {
      props: { streamUrl: 'https://example.test/hls/item/master.m3u8', title: 'T', playing: false },
      attachTo: document.body,
    })

  it('does not reload the source when hls.js re-attaches to recover', async () => {
    // The regression: MEDIA_ATTACHED was a sticky listener, so hls.js's own
    // recovery (detach, attach, startLoad at the saved position) triggered a
    // second loadSource. loadSource is the only thing that fires
    // MANIFEST_LOADING, and that handler resets startPosition to 0, so the
    // library restored the playhead and the app discarded it one event later.
    // Playback resumed at the top of the stream, and the restarted client
    // broadcast that position as a seek, taking the whole party with it.
    const wrapper = mountPlayer()
    await flushPromises()
    const hls = instances.at(-1)!
    expect(hls.loadSource).toHaveBeenCalledTimes(1)

    hls.recoverMediaError(412.5)
    await flushPromises()

    expect(hls.loadSource).toHaveBeenCalledTimes(1)
    expect(hls.startLoad).toHaveBeenCalledWith(412.5)
    wrapper.unmount()
  })

  it('still loads the source when the stream url changes', async () => {
    // The fix must not cost a legitimate reload. attachStream destroys the
    // instance and builds a new one per stream change, so each gets its own
    // one-shot listener and its own single load.
    const wrapper = mountPlayer()
    await flushPromises()
    const first = instances.at(-1)!
    expect(first.loadSource).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ streamUrl: 'https://example.test/hls/item/other.m3u8' })
    await flushPromises()

    expect(first.destroy).toHaveBeenCalled()
    const second = instances.at(-1)!
    expect(second).not.toBe(first)
    expect(second.loadSource).toHaveBeenCalledWith('https://example.test/hls/item/other.m3u8')
    expect(second.loadSource).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
