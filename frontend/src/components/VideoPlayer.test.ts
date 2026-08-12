import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import VideoPlayer from './VideoPlayer.vue'

const hlsMock = vi.hoisted(() => ({
  supported: false,
  constructed: vi.fn(),
}))

vi.mock('hls.js', () => ({
  default: class FakeHls {
    static Events = {
      MEDIA_ATTACHED: 'mediaAttached',
      MANIFEST_PARSED: 'manifestParsed',
      ERROR: 'error',
    }

    static ErrorTypes = {
      NETWORK_ERROR: 'networkError',
      MEDIA_ERROR: 'mediaError',
    }

    static isSupported() {
      return hlsMock.supported
    }

    constructor() {
      hlsMock.constructed()
    }

    attachMedia() {}

    loadSource() {}

    on() {}

    destroy() {}
  },
}))

describe('VideoPlayer native HLS support', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    hlsMock.supported = false
    hlsMock.constructed.mockClear()
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('probably')
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  })

  it('prefers native HLS on iPhone when Hls.js also reports support', () => {
    hlsMock.supported = true
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('')
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15',
    )

    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: false,
      },
    })

    expect(wrapper.get('video').attributes('src')).toBe('/hls/native/master.m3u8')
    expect(hlsMock.constructed).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    [
      'Android Chrome',
      'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36',
    ],
    [
      'desktop Safari',
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15',
    ],
  ])('keeps %s on Hls.js when MediaSource is supported', (_browser, userAgent) => {
    hlsMock.supported = true
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(userAgent)

    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/managed/master.m3u8',
        title: 'Movie',
        playing: false,
      },
    })

    expect(hlsMock.constructed).toHaveBeenCalledOnce()
    expect(wrapper.get('video').attributes('src')).toBeUndefined()
    wrapper.unmount()
  })

  it('reports iOS autoplay blocking through the public component event', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
      new DOMException('User gesture required', 'NotAllowedError'),
    )

    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: true,
      },
    })

    await wrapper.get('video').trigger('loadedmetadata')
    await Promise.resolve()

    expect(wrapper.emitted('autoplay-blocked')).toHaveLength(1)
    wrapper.unmount()
  })

  it('forwards a play started while the stream-settle guard is active', async () => {
    vi.useFakeTimers()
    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: false,
      },
    })
    const video = wrapper.get('video').element as HTMLVideoElement
    let paused = true
    Object.defineProperty(video, 'paused', {
      configurable: true,
      get: () => paused,
    })

    await wrapper.get('video').trigger('loadedmetadata')
    paused = false
    await wrapper.get('video').trigger('play')
    expect(wrapper.emitted('play')).toBeUndefined()

    await vi.advanceTimersByTimeAsync(500)
    expect(wrapper.emitted('play')).toHaveLength(1)

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('releases the native HLS request when the player unmounts', () => {
    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: false,
      },
    })
    const video = wrapper.get('video').element as HTMLVideoElement
    expect(video.getAttribute('src')).toBe('/hls/native/master.m3u8')

    wrapper.unmount()

    expect(video.getAttribute('src')).toBeNull()
    expect(video.load).toHaveBeenCalledOnce()
  })
})
